"""Durable request outbox. No model, shell, build, or source-write operations.

The versioned payload is the boundary for a future code-dev adapter. Reading or
exporting it is not delivery acknowledgement and never changes request state.
"""
import copy
import json
import os
from pathlib import Path
import secrets
import tempfile


class RequestIntake:
    MAX_BYTES = 64 * 1024 * 1024
    MAX_RECORDS = 200

    def __init__(self, context):
        self.c = context

    @property
    def path(self):
        return Path(os.environ.get("AX_REQUESTS_FILE", str(
            self.c["CONFIG_FILE"].with_name("requests.json")))).expanduser()

    def fail(self, message, status=400):
        raise self.c["ApiError"](message, status)

    def read(self):
        path = self.path
        if path.is_symlink():
            self.fail("요청 저장 파일은 심볼릭 링크일 수 없습니다.", 409)
        if not path.exists():
            return {"version": 1, "requests": []}
        try:
            if path.stat().st_size > self.MAX_BYTES:
                self.fail("요청 저장 용량 한도를 초과했습니다.", 409)
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or not isinstance(data.get("requests"), list)
                    or any(not isinstance(r, dict) or not isinstance(r.get("payload"), dict)
                           or not isinstance(r.get("id"), str)
                           or "environment" not in r["payload"] for r in data["requests"])):
                self.fail("요청 저장 파일 형식이 올바르지 않습니다.", 409)
            return data
        except (OSError, UnicodeError, ValueError):
            self.fail("요청 저장 파일을 읽을 수 없습니다. 파일을 확인하세요.", 409)

    def write(self, data):
        raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if len(raw.encode("utf-8")) > self.MAX_BYTES:
            self.fail("요청 저장 용량 한도에 도달했습니다.", 429)
        path = self.path
        if path.is_symlink():
            self.fail("요청 저장 파일은 심볼릭 링크일 수 없습니다.", 409)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".ax-request-", delete=False) as stream:
                temp = Path(stream.name)
                os.chmod(temp, 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if temp and temp.exists():
                temp.unlink()

    def summary(self, record, full=False):
        payload = record["payload"]
        profile = self.c["profile_for"](Path(payload["workspace"]))
        runs = record.get("cli_runs", [])
        result = {"id": record["id"], "status": runs[-1]["status"] if runs else "waiting_for_agent",
                  "created_at": payload["created_at"], "workspace": payload["workspace"],
                  "origin": payload["origin"], **payload["request"],
                  "profile_revision": payload["environment"]["revision"],
                  "configuration_stale": not profile or profile.get("revision") != payload["environment"]["revision"],
                  "agent_available": False}
        if full:
            result["payload"] = copy.deepcopy(payload)
            result["cli_runs"] = copy.deepcopy(runs)
        else:
            result.pop("source_content", None)
        return result

    def list(self):
        with self.c["LOCK"]:
            return [self.summary(item) for item in self.read()["requests"]]

    def get(self, ident, for_agent=False):
        with self.c["LOCK"]:
            item = next((r for r in self.read()["requests"] if r["id"] == ident), None)
            if item is None:
                self.fail("요청을 찾을 수 없습니다.", 404)
            result = self.summary(item, full=True)
            if for_agent and result["configuration_stale"]:
                self.fail("개발 환경이 변경되었습니다. 현재 설정으로 요청을 다시 접수하세요.", 409)
            return result

    def create(self, raw, agent=False):
        allowed = {"workspace", "instruction", "prompt", "source_kind", "source_ref",
                   "source_content", "source_agent", "upstream_run_id", "target",
                   "expected_revision", "idempotency_key", "auto_generate"}
        if set(raw) - allowed:
            self.fail("알 수 없는 요청 항목이 있습니다.")
        if "auto_generate" in raw and raw["auto_generate"] is not False:
            self.fail("code-dev agent는 아직 연결되지 않았습니다. auto_generate는 false만 허용합니다.", 409)
        root = self.c["resolve_workspace"](raw.get("workspace"))
        instruction = raw.get("instruction", raw.get("prompt", ""))
        if not isinstance(instruction, str) or not 5 <= len(instruction.strip()) <= 4000 or "\x00" in instruction:
            self.fail("개발 요청은 5~4000자로 입력하세요.")
        meta = self.c["request_context"](raw, agent=agent)
        if agent and not meta["source_agent"]:
            self.fail("source_agent를 입력하세요.")
        target = raw.get("target", "")
        if not isinstance(target, str):
            self.fail("target은 상대 파일 경로 문자열이어야 합니다.")
        key = raw.get("idempotency_key", "")
        if not isinstance(key, str) or len(key) > 160 or "\x00" in key:
            self.fail("idempotency_key는 160자 이하 문자열이어야 합니다.")
        request = {"instruction": instruction.strip(), "target": target, **meta}
        origin = "agent" if agent else "human"
        fingerprint = self.c["sha"](json.dumps({"workspace": str(root), "origin": origin,
            "request": request, "expected_revision": raw.get("expected_revision")}, sort_keys=True))
        with self.c["LOCK"]:
            store = self.read()
            if key:
                prior = next((r for r in store["requests"] if r["idempotency_key"] == key
                              and r["payload"]["workspace"] == str(root)
                              and r["payload"]["origin"] == origin
                              and r["payload"]["request"]["source_agent"] == meta["source_agent"]), None)
                if prior:
                    if prior["fingerprint"] != fingerprint:
                        self.fail("같은 idempotency_key에 다른 요청을 사용할 수 없습니다.", 409)
                    return self.summary(prior, full=True)
            profile = self.c["require_profile"](root)
            if (not agent or "expected_revision" in raw) and raw.get("expected_revision") != profile["revision"]:
                self.fail("개발 환경이 변경되었습니다. 환경을 다시 연결한 후 접수하세요.", 409)
            scan = self.c["scan_workspace"](root, profile)
            if scan["stats"]["truncated"]:
                self.fail("파일 탐색이 제한되었습니다. 수정 허용 경로를 좁힌 뒤 접수하세요.", 409)
            if not scan["files"]:
                self.fail("수정 가능한 파일이 없습니다. 수정 허용 경로를 확인하세요.", 409)
            if target:
                self.c["resolve_target"](root, target)
                if target not in {f["path"] for f in scan["files"]}:
                    self.fail("target이 수정 허용 파일 목록에 없습니다.", 403)
            if len(store["requests"]) >= self.MAX_RECORDS:
                self.fail("요청 보관 한도에 도달했습니다. requests.json을 백업하고 정리하세요.", 429)
            ident = secrets.token_hex(12)
            payload = {"schema_version": "ax.code-dev.request.v1", "request_id": ident,
                       "recipient": "code-dev", "created_at": self.c["timestamp"](),
                       "origin": origin, "workspace": str(root),
                       "git_branch": self.c["git_branch"](root), "request": request,
                       "environment": copy.deepcopy(profile),
                       "scope": {"editable_files": scan["files"], "scan": scan["stats"],
                                 "read_boundary": str(root), "write_policy": "explicit_allowlist_only",
                                 "revalidate_before_execution": True},
                       "execution": {"agent_implemented": False, "build_executed": False,
                                     "source_modified": False, "approval_required_for_changes": True}}
            record = {"id": ident, "idempotency_key": key, "fingerprint": fingerprint, "payload": payload}
            store["requests"].insert(0, record)
            self.write(store)
            return self.summary(record, full=True)
