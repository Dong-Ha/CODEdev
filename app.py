#!/usr/bin/env python3
"""AX Code-Dev GUI: Claude Code CLI proposals with explicit human approval.

Requires Python 3.9+. Uses only the standard library for the web server.
The optional Claude Code CLI may contact the user-configured Anthropic/provider service.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import secrets
import stat
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
DEMO = BASE / "demo_workspace"
HOST = "127.0.0.1"
PORT = int(os.environ.get("AX_PORT", "8765"))
MAX_FILE_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 24 * 1024
MAX_FILES = 1500
MAX_HISTORY = 35
CONFIG_FILE = Path(os.environ.get("AX_CONFIG_FILE", str(Path.home() / ".config" / "ax-code-dev" / "profiles.json"))).expanduser()
CSRF = secrets.token_urlsafe(32)
LOCK = threading.RLock()
PROPOSALS: dict[str, dict] = {}
RECENT: list[str] = []
EXTENSIONS = {".c", ".h", ".cpp", ".cc", ".hpp", ".py", ".rs", ".go",
              ".java", ".kt", ".sh", ".md", ".txt", ".json", ".yaml",
              ".yml", ".toml", ".js", ".jsx", ".ts", ".tsx"}
SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", "build", "out", "dist",
             "target", ".venv", "venv", "__pycache__", ".next", ".gradle",
             "vendor", ".idea", ".vscode", ".ax-code-dev"}
PROFILE_FIELDS = {"project_name", "project_type", "build_dir", "architecture",
                  "cross_compile", "build_command", "build_env", "editable_paths",
                  "blocked_paths", "change_notes", "code_guidelines"}
PROJECT_TYPES = {"linux-kernel", "generic"}


def default_profile(root: Path) -> dict:
    """First-run form defaults, *not* a saved/authorized configuration."""
    kernel = root == DEMO.resolve() or (root / "drivers" / "power" / "supply").is_dir()
    return {
        "project_name": root.name,
        "project_type": "linux-kernel" if kernel else "generic",
        "build_dir": ".",
        "architecture": "arm64" if kernel else "",
        "cross_compile": "aarch64-linux-gnu-" if kernel else "",
        "build_command": "make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image dtbs modules" if kernel else "",
        "build_env": "",
        "editable_paths": "drivers/power/supply/**\ninclude/linux/power/**" if kernel else "",
        "blocked_paths": "**/*.key\n**/secrets/**\n**/.env",
        "change_notes": "IFPMIC Charger / Fuel Gauge 변경 대상 함수와 의도된 동작을 작업 요청에 명시" if kernel else "",
        "code_guidelines": "기존 커널 스타일 유지, 오류 경로/리소스 정리 확인, 관련 없는 로직 수정 금지" if kernel else "",
    }


def read_store() -> dict:
    if not CONFIG_FILE.exists():
        return {"profiles": {}, "last_workspace": ""}
    if CONFIG_FILE.is_symlink():
        raise ApiError("설정 파일은 심볼릭 링크일 수 없습니다.", 409)
    try:
        if CONFIG_FILE.stat().st_size > 1_000_000:
            raise ApiError("설정 파일 용량이 너무 큽니다.", 409)
        with CONFIG_FILE.open(encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ApiError(f"로컬 설정 파일을 읽을 수 없습니다: {exc}", 409)
    if not isinstance(store, dict) or not isinstance(store.get("profiles"), dict):
        raise ApiError("로컬 설정 파일 형식이 올바르지 않습니다.", 409)
    return store


def write_store(store: dict) -> None:
    directory = CONFIG_FILE.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if CONFIG_FILE.is_symlink():
        raise ApiError("설정 파일은 심볼릭 링크일 수 없습니다.", 409)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".ax-profile-", delete=False) as f:
            tmp = Path(f.name)
            os.chmod(tmp, 0o600)
            json.dump(store, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_FILE)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def profile_for(root: Path) -> dict | None:
    profile = read_store().get("profiles", {}).get(str(root))
    return profile if isinstance(profile, dict) else None


def validate_relative_dir(root: Path, raw: str) -> str:
    if not raw or raw == ".":
        return "."
    if raw.startswith("/") or "\\" in raw or "\x00" in raw:
        raise ApiError("빌드 작업 폴더는 프로젝트 내부 상대 경로만 지정하세요.")
    parts = Path(raw).parts
    if any(p in {"..", ""} for p in parts):
        raise ApiError("빌드 작업 폴더에 상위 경로(..)를 사용할 수 없습니다.")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ApiError("빌드 작업 폴더에 심볼릭 링크를 사용할 수 없습니다.")
    if not current.is_dir():
        raise ApiError("빌드 작업 폴더가 존재하지 않습니다. 프로젝트 안의 실제 디렉터리를 선택하세요.")
    return Path(*parts).as_posix()


def parse_patterns(raw: str, required: bool = False) -> list[str]:
    patterns = []
    for line in raw.splitlines():
        pat = line.strip()
        if not pat or pat.startswith("#"):
            continue
        if (len(pat) > 250 or pat.startswith("/") or "\\" in pat or "\x00" in pat
                or any(p == ".." for p in pat.split("/")) or "[" in pat or "]" in pat):
            raise ApiError(f"허용할 수 없는 경로 패턴입니다: {pat[:90]}")
        patterns.append(pat.rstrip("/"))
    if len(patterns) > 50:
        raise ApiError("경로 규칙은 최대 50개까지 등록할 수 있습니다.")
    if required and not patterns:
        raise ApiError("수정 허용 경로를 최소 1개 지정하세요.")
    return patterns


def glob_matches(pattern: str, relative: str) -> bool:
    """POSIX globs: * = one segment; ** = any nested segments."""
    if pattern.endswith("/**") and (relative == pattern[:-3] or relative.startswith(pattern[:-2])):
        return True
    pattern = pattern.lstrip("./")
    reg = ["^"]
    i = 0
    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            reg.append("(?:.*/)?")
            i += 3
        elif pattern[i:i + 2] == "**":
            reg.append(".*")
            i += 2
        elif pattern[i] == "*":
            reg.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            reg.append("[^/]")
            i += 1
        else:
            reg.append(re.escape(pattern[i]))
            i += 1
    return re.fullmatch("".join(reg) + "$", relative) is not None


def editable(profile: dict, target: str) -> bool:
    includes = parse_patterns(profile.get("editable_paths", ""), required=True)
    excludes = parse_patterns(profile.get("blocked_paths", ""))
    return any(glob_matches(p, target) for p in includes) and not any(
        glob_matches(p, target) for p in excludes)


def require_profile(root: Path) -> dict:
    profile = profile_for(root)
    if profile is None:
        raise ApiError("환경 설정 페이지에서 프로젝트 설정을 저장한 후 진행하세요.", 409)
    return profile


def require_editable(root: Path, target: str, profile: dict | None = None) -> dict:
    profile = profile or require_profile(root)
    if not editable(profile, target):
        raise ApiError("환경 설정의 수정 허용 범위 밖이거나 제외된 파일입니다.", 403)
    return profile


def configured_files(root: Path, profile: dict | None, files: list[dict] | None = None) -> list[dict]:
    files = collect_files(root) if files is None else files
    return [f for f in files if editable(profile, f["path"])] if profile else []


def save_profile(root: Path, raw: object, expected_revision: object = None) -> dict:
    if not isinstance(raw, dict):
        raise ApiError("환경 설정 정보를 입력하세요.")
    if set(raw) - PROFILE_FIELDS:
        raise ApiError("알 수 없는 환경 설정 항목이 있습니다.")
    config = {}
    for key in PROFILE_FIELDS:
        val = raw.get(key, "")
        if not isinstance(val, str):
            raise ApiError(f"{key}는 문자열이어야 합니다.")
        limit = 4000 if key in {"build_command", "build_env", "change_notes", "code_guidelines"} else 1500
        if len(val) > limit or "\x00" in val:
            raise ApiError(f"{key} 입력이 너무 깁니다.")
        config[key] = val.strip()
    if not config["project_name"] or not config["build_command"]:
        raise ApiError("프로젝트명과 빌드 명령어는 필수입니다.")
    if config["project_type"] not in PROJECT_TYPES:
        raise ApiError("프로젝트 유형이 올바르지 않습니다.")
    config["build_dir"] = validate_relative_dir(root, config["build_dir"])
    parse_patterns(config["editable_paths"], required=True)
    parse_patterns(config["blocked_paths"])
    for key in ("architecture", "cross_compile"):
        if config[key] and not re.fullmatch(r"[a-zA-Z0-9_.+/@:-]{1,180}", config[key]):
            raise ApiError(f"{key} 값에는 공백/셸 제어 문자를 사용할 수 없습니다.")
    for line in config["build_env"].splitlines():
        if line.strip() and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=[^\r\n]*", line.strip()):
            raise ApiError("추가 환경변수는 KEY=value 형식으로 한 줄씩 입력하세요.")
    with LOCK:
        store = read_store()
        previous = store["profiles"].get(str(root))
        if previous and expected_revision != previous.get("revision"):
            raise ApiError("다른 탭에서 설정이 변경되었습니다. 새로고침 후 다시 편집하세요.", 409)
        if not previous and expected_revision not in {None, ""}:
            raise ApiError("설정 버전이 달라졌습니다. 다시 연결하세요.", 409)
        config["revision"] = secrets.token_hex(10)
        config["updated_at"] = timestamp()
        store["profiles"][str(root)] = config
        store["last_workspace"] = str(root)
        write_store(store)
    return config


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_utf8(path: Path) -> str:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ApiError(f"파일이 {MAX_FILE_BYTES // 1024}KB 제한을 초과합니다.")
    if not path.is_file():
        raise ApiError("일반 파일만 수정할 수 있습니다.")
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            content = fh.read()
    except (UnicodeError, OSError):
        raise ApiError("UTF-8 텍스트 파일만 지원합니다.")
    if "\x00" in content:
        raise ApiError("바이너리 파일은 지원하지 않습니다.")
    return content


def resolve_workspace(raw_path: object) -> Path:
    if not isinstance(raw_path, str) or len(raw_path) > 1024 or not raw_path.strip():
        raise ApiError("유효한 로컬 워크스페이스 경로를 입력하세요.")
    raw = Path(raw_path.strip()).expanduser()
    if raw.is_symlink():
        raise ApiError("심볼릭 링크인 워크스페이스는 지원하지 않습니다.")
    try:
        root = raw.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ApiError("워크스페이스 경로가 존재하지 않습니다.")
    if not root.is_dir():
        raise ApiError("워크스페이스는 디렉터리여야 합니다.")
    # Don't accidentally open huge top-level directories.
    if str(root) in {"/", "/home", "/mnt", "/etc", "/usr", "/var", "/tmp"}:
        raise ApiError("프로젝트 루트 디렉터리를 선택하세요. 시스템 상위 디렉터리는 사용할 수 없습니다.")
    return root


def collect_files(root: Path) -> list[dict]:
    found = []
    for base, dirs, files in os.walk(root, followlinks=False):
        path = Path(base)
        depth = len(path.relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and not (path / d).is_symlink()) if depth < 9 else []
        for name in sorted(files):
            if name.startswith(".") or Path(name).suffix.lower() not in EXTENSIONS:
                continue
            path_file = path / name
            if path_file.is_symlink():
                continue
            try:
                s = path_file.stat()
            except OSError:
                continue
            if not stat.S_ISREG(s.st_mode) or s.st_size > MAX_FILE_BYTES:
                continue
            found.append({"path": path_file.relative_to(root).as_posix(), "size": s.st_size})
            if len(found) >= MAX_FILES:
                return found
    return found


def resolve_target(root: Path, target: object) -> Path:
    if not isinstance(target, str) or not target or len(target) > 500:
        raise ApiError("파일 경로가 올바르지 않습니다.")
    p = Path(target)
    if p.is_absolute() or ".." in p.parts or any(piece.startswith(".") for piece in p.parts):
        raise ApiError("프로젝트 내부의 상대 경로만 허용됩니다.")
    if p.suffix.lower() not in EXTENSIONS or any(part in SKIP_DIRS for part in p.parts):
        raise ApiError("지원하지 않는 파일 경로입니다.")
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ApiError("심볼릭 링크를 거치는 파일은 지원하지 않습니다.")
    full = (root / p).resolve(strict=True)
    if not full.is_relative_to(root):
        raise ApiError("프로젝트 밖 파일에 접근할 수 없습니다.")
    return full


def git_branch(root: Path) -> str:
    if not (root / ".git").exists():
        return "Git 미연결"
    try:
        output = subprocess.run(["git", "-C", str(root), "branch", "--show-current"],
                                capture_output=True, text=True, check=False, timeout=3)
        if output.returncode == 0:
            return output.stdout.strip() or "(detached HEAD)"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "Git 확인 불가"


def create_diff(path: str, old: str, new: str) -> tuple[list[dict], int, int]:
    lines = list(difflib.unified_diff(old.splitlines(keepends=True),
                                     new.splitlines(keepends=True),
                                     fromfile=f"a/{path}", tofile=f"b/{path}", n=4))
    changes, plus, minus = [], 0, 0
    for line in lines:
        kind = "context"
        if line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("---") or line.startswith("+++"):
            kind = "meta"
        elif line.startswith("+"):
            kind, plus = "add", plus + 1
        elif line.startswith("-"):
            kind, minus = "remove", minus + 1
        changes.append({"kind": kind, "text": line.rstrip("\r\n")})
    return changes, plus, minus


def demo_proposal(root: Path, target: str, original: str) -> dict:
    if root != DEMO.resolve() or target != "drivers/power/supply/ax_ifpmic_charger.c":
        raise ApiError("데모 엔진은 제공된 IFPMIC 예제 파일만 수정합니다. 실제 프로젝트는 Claude Code 모드를 사용하세요.")
    old = "    chip->input_current_ma = current_ma;\n    return 0;\n"
    new = ("    /* Reject invalid requests before updating the cached current. */\n"
           "    if (current_ma < 0 || current_ma > AX_IFPMIC_INPUT_MAX_MA)\n"
           "        return -EINVAL;\n\n"
           "    chip->input_current_ma = current_ma;\n    return 0;\n")
    if old not in original:
        raise ApiError("예제 파일이 이미 수정되었습니다. '되돌리기' 후 다시 실행하세요.")
    return {
        "summary": "충전 입력 전류의 범위 검증 추가",
        "rationale": "음수 및 허용 상한을 초과한 값은 캐시 변경 전에 -EINVAL로 거부합니다.",
        "risk": "낮음 (예제용 추정)",
        "checks": ["0mA, 최대 허용값, 음수, 최대값 초과 경계조건 확인",
                   "기존 정상 입력 동작 유지 여부 코드 리뷰", "실제 보드/커널 빌드는 실행하지 않음"],
        "new_content": original.replace(old, new, 1)
    }


# Claude Code receives task data via stdin only. No repository filesystem permissions
# are granted; the GUI remains the sole writer after explicit review approval.
CLAUDE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "rationale": {"type": "string"},
        "risk": {"type": "string"},
        "checks": {"type": "array", "items": {"type": "string"}},
        "new_content": {"type": "string"},
    },
    "required": ["summary", "rationale", "risk", "checks", "new_content"],
    "additionalProperties": False,
}


def claude_status() -> dict:
    # Only checks the executable; authentication is checked by Claude Code itself.
    binary = shutil.which("claude")
    return {"installed": binary is not None,
            "note": ("Claude Code CLI 감지됨 · 인증 여부는 실행 시 확인" if binary else
                     "WSL/Linux에 Claude Code CLI를 설치하고 'claude auth login'을 실행하세요.")}


def call_claude(prompt: str, target: str, original: str, profile: dict) -> dict:
    binary = shutil.which("claude")
    if not binary:
        raise ApiError("Claude Code CLI를 찾지 못했습니다. 서버가 실행되는 WSL/Linux에 설치하세요.", 503)
    instructions = BASE / "agents" / "code-dev.md"
    context = {k: profile.get(k, "") for k in PROFILE_FIELDS}
    # Build recipe is task context, never a shell command; the selected source
    # is sent in stdin, not made accessible to Claude's file-editing tools.
    task = (f"Task:\n{prompt}\n\n"
            "Environment configuration (reference only; never run build commands):\n"
            f"{json.dumps(context, ensure_ascii=False)}\n\nTarget path: {target}\n"
            f"File contents START\n{original}\nFile contents END\n"
            "Return a complete revised file in new_content; do not modify files.")
    cmd = [binary, "-p", "Return a structured code change proposal for the task in stdin.",
           "--output-format", "json", "--json-schema", json.dumps(CLAUDE_RESULT_SCHEMA),
           "--system-prompt-file", str(instructions),
           "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
           "--permission-mode", "plan", "--no-session-persistence", "--max-turns", "1"]
    try:
        # An isolated cwd avoids loading project-local context or hooks from the
        # target repository; user-level Claude settings can still apply.
        with tempfile.TemporaryDirectory(prefix="ax-claude-") as scratch:
            output = subprocess.run(cmd, input=task, cwd=scratch, capture_output=True,
                                    text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ApiError("Claude Code 응답 시간(180초)이 초과되었습니다.", 504) from exc
    except OSError as exc:
        raise ApiError("Claude Code CLI를 실행할 수 없습니다. 설치 상태와 실행 권한을 확인하세요.", 503) from exc
    if output.returncode != 0:
        # stderr may contain snippets of internal code, configuration, or auth
        # state: never return it to the web client.
        raise ApiError(f"Claude Code 실행 실패 (exit {output.returncode}). CLI 인증 상태를 'claude auth status'로 확인하세요.", 502)
    if len(output.stdout) > 1_200_000:
        raise ApiError("Claude Code 응답 크기가 제한을 초과했습니다.", 422)
    try:
        envelope = json.loads(output.stdout)
        result = envelope.get("structured_output") if isinstance(envelope, dict) else None
        if not isinstance(result, dict) and isinstance(envelope, dict):
            raw = envelope.get("result")
            result = json.loads(raw) if isinstance(raw, str) else None
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError("Claude Code가 유효한 JSON 변경안을 반환하지 않았습니다.", 422) from exc
    if not isinstance(result, dict) or not isinstance(result.get("new_content"), str):
        raise ApiError("Claude Code 출력에 전체 파일 내용(new_content)이 없습니다.", 422)
    return result


def validate_result(result: dict, original: str) -> tuple[str, str, str, list[str], str]:
    revised = result.get("new_content")
    if not isinstance(revised, str) or not revised or "\x00" in revised:
        raise ApiError("생성된 코드가 유효한 텍스트가 아닙니다.", 422)
    if len(revised.encode("utf-8")) > MAX_FILE_BYTES:
        raise ApiError("생성된 파일이 64KB 크기 제한을 초과합니다.", 422)
    if revised == original:
        raise ApiError("모델이 변경 사항을 생성하지 않았습니다. 요청을 구체화해 다시 시도하세요.", 422)
    def clipped(v: object, fallback: str) -> str:
        return str(v)[:320] if isinstance(v, str) and v.strip() else fallback
    raw_checks = result.get("checks")
    checks = [str(s)[:160] for s in raw_checks[:6] if isinstance(s, str)] if isinstance(raw_checks, list) else []
    return (clipped(result.get("summary"), "코드 변경안"),
            clipped(result.get("rationale"), "변경 내용을 검토하세요."),
            clipped(result.get("risk"), "검토 필요 (모델 자체 평가)"),
            checks or ["Diff 전체 확인", "변경 적용 후 수동 검증 필요"], revised)


def to_public(p: dict, full: bool = False) -> dict:
    public = {k: p[k] for k in ("id", "workspace", "target", "engine", "prompt",
                                 "summary", "rationale", "risk", "checks", "plus", "minus",
                                 "status", "created_at", "activity")}
    if full:
        public.update({"diff": p["diff"], "original_content": p["original"],
                       "new_content": p["new_content"]})
    return public


def add_activity(p: dict, msg: str) -> None:
    p["activity"].append({"at": timestamp(), "message": msg})


def propose(body: dict) -> dict:
    root = resolve_workspace(body.get("workspace"))
    target = body.get("target")
    file = resolve_target(root, target)
    profile = require_editable(root, str(target))
    original = read_utf8(file)
    prompt = body.get("prompt", "")
    if not isinstance(prompt, str) or not 5 <= len(prompt.strip()) <= 4000:
        raise ApiError("작업 요청은 5~4000자로 작성하세요.")
    engine = body.get("engine", "claude")
    if engine not in {"demo", "claude"}:
        raise ApiError("지원하지 않는 에이전트 모드입니다.")
    result = demo_proposal(root, str(target), original) if engine == "demo" else \
             call_claude(prompt, str(target), original, profile)
    summary, rationale, risk, checks, revised = validate_result(result, original)
    diff, plus, minus = create_diff(str(target), original, revised)
    if not plus and not minus:
        raise ApiError("공백이나 줄바꿈을 포함한 실제 변경이 없습니다.", 422)
    p = {"id": secrets.token_hex(5), "workspace": str(root), "target": str(target),
         "config_revision": profile["revision"],
         "engine": engine, "prompt": prompt.strip(), "summary": summary,
         "rationale": rationale, "risk": risk, "checks": checks, "plus": plus, "minus": minus,
         "status": "review", "created_at": timestamp(), "original": original,
         "original_hash": sha(original), "new_content": revised, "new_hash": sha(revised),
         "diff": diff, "activity": []}
    add_activity(p, "변경 제안 생성 · 실제 파일 미수정")
    add_activity(p, f"변경 범위 분석 · +{plus} / -{minus} 라인")
    with LOCK:
        PROPOSALS[p["id"]] = p
        RECENT.insert(0, p["id"])
        while len(RECENT) > MAX_HISTORY:
            PROPOSALS.pop(RECENT.pop(), None)
    return to_public(p, True)


def atomic_write(path: Path, data: str) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".ax-update-", suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, original_mode)
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def change_status(body: dict, action: str) -> dict:
    ident = body.get("id")
    with LOCK:
        p = PROPOSALS.get(ident)
        if not p:
            raise ApiError("제안이 존재하지 않거나 서버 재시작으로 만료되었습니다.", 404)
        if action == "apply" and p["status"] != "review":
            raise ApiError("검토 상태인 제안만 승인할 수 있습니다.", 409)
        if action == "reject" and p["status"] != "review":
            raise ApiError("검토 상태인 제안만 반려할 수 있습니다.", 409)
        if action == "undo" and p["status"] != "applied":
            raise ApiError("반영된 제안만 되돌릴 수 있습니다.", 409)
        if action in {"apply", "undo"}:
            root = resolve_workspace(p["workspace"])
            path = resolve_target(root, p["target"])
            if action == "apply":
                current_profile = require_editable(root, p["target"])
                if current_profile["revision"] != p["config_revision"]:
                    raise ApiError("제안 생성 후 개발 환경 설정이 변경되었습니다. 변경안을 다시 생성하세요.", 409)
            # Undo is still permitted after a scope change to restore a prior approved edit.
            current = read_utf8(path)
            expected = p["original_hash"] if action == "apply" else p["new_hash"]
            if sha(current) != expected:
                raise ApiError("파일이 제안 이후 외부에서 변경되었습니다. 덮어쓰기를 중단했습니다.", 409)
            atomic_write(path, p["new_content"] if action == "apply" else p["original"])
            p["status"] = "applied" if action == "apply" else "undone"
            add_activity(p, "사용자 승인 · 로컬 파일 반영 완료" if action == "apply" else
                         "사용자 요청 · 반영 내용 되돌리기 완료")
        else:
            p["status"] = "rejected"
            add_activity(p, "사용자 반려 · 원본 파일 유지")
        return to_public(p, True)


class Handler(BaseHTTPRequestHandler):
    server_version = "AXCodeDevMVP/0.3"
    def _headers(self, status: int, mime: str = "application/json; charset=utf-8", length: int = 0):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _json(self, status: int, data: dict):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._headers(status, length=len(raw))
        self.wfile.write(raw)

    def _error(self, exc: Exception):
        status = exc.status if isinstance(exc, ApiError) else 500
        message = str(exc) if isinstance(exc, ApiError) else "서버 내부 오류가 발생했습니다. 서버 터미널 로그를 확인하세요."
        self._json(status, {"ok": False, "error": message})
        if not isinstance(exc, ApiError):
            self.log_error("Internal error: %r", exc)

    def _origin_ok(self) -> bool:
        hostname = self.headers.get("Host", "")
        if hostname not in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}:
            return False
        return True

    def do_GET(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "로컬 호스트 접속만 허용됩니다."})
        route = urlparse(self.path).path
        if route == "/api/bootstrap":
            store = read_store()
            return self._json(200, {"ok": True, "token": CSRF, "demo_path": str(DEMO.resolve()),
                                    "last_workspace": store.get("last_workspace", ""),
                                    "config_file": str(CONFIG_FILE),
                                    "version": "0.3.0", "limitations": {"max_file_kb": 64}})
        if route == "/api/claude/status":
            return self._json(200, {"ok": True, **claude_status()})
        if route == "/api/history":
            with LOCK:
                return self._json(200, {"ok": True, "history": [to_public(PROPOSALS[i]) for i in RECENT]})
        if route.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "찾을 수 없는 API입니다."})
        asset = {"/": "index.html", "/index.html": "index.html", "/style.css": "style.css",
                 "/app.js": "app.js"}.get(route)
        if not asset:
            return self._headers(404, "text/plain", 0)
        path = WEB / asset
        if not path.exists():
            return self._headers(404, "text/plain", 0)
        data = path.read_bytes()
        mime = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
                "js": "application/javascript; charset=utf-8"}[path.suffix[1:]]
        self._headers(200, mime, len(data))
        self.wfile.write(data)

    def do_POST(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "허용되지 않은 Origin/Host입니다."})
        if self.headers.get("X-AX-Token") != CSRF:
            return self._json(403, {"ok": False, "error": "요청 검증 토큰이 누락되었습니다."})
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(415, {"ok": False, "error": "JSON 요청만 지원합니다."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise ApiError("요청 본문이 비어 있거나 크기 제한을 초과합니다.", 413)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ApiError("JSON 객체를 전달하세요.")
            route = urlparse(self.path).path
            if route == "/api/workspace":
                root = resolve_workspace(body.get("path"))
                profile = profile_for(root)
                all_files = collect_files(root)
                allowed = configured_files(root, profile, all_files)
                return self._json(200, {"ok": True, "path": str(root), "name": root.name,
                                        "branch": git_branch(root), "files": allowed,
                                        "total_files": len(all_files),
                                        "configured": profile is not None,
                                        "config": profile if profile else default_profile(root),
                                        "is_demo": root == DEMO.resolve()})
            if route == "/api/config/save":
                root = resolve_workspace(body.get("workspace"))
                profile = save_profile(root, body.get("config"), body.get("expected_revision"))
                allowed = configured_files(root, profile)
                return self._json(200, {"ok": True, "config": profile,
                                        "editable_files": len(allowed), "workspace": str(root)})
            if route == "/api/file":
                root = resolve_workspace(body.get("workspace"))
                path = resolve_target(root, body.get("target"))
                require_editable(root, str(body.get("target")))
                return self._json(200, {"ok": True, "content": read_utf8(path)})
            if route == "/api/propose":
                return self._json(200, {"ok": True, "proposal": propose(body)})
            if route in {"/api/apply", "/api/reject", "/api/undo"}:
                action = route.rsplit("/", 1)[1]
                return self._json(200, {"ok": True, "proposal": change_status(body, action)})
            if route == "/api/proposal":
                with LOCK:
                    p = PROPOSALS.get(body.get("id"))
                    if not p:
                        raise ApiError("제안이 존재하지 않습니다.", 404)
                    return self._json(200, {"ok": True, "proposal": to_public(p, True)})
            raise ApiError("찾을 수 없는 API입니다.", 404)
        except (ApiError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            self._error(exc if isinstance(exc, ApiError) else ApiError("요청 데이터가 올바르지 않습니다."))
        except Exception as exc:
            self._error(exc)

    def log_message(self, fmt: str, *args) -> None:
        if self.path.startswith("/api/"):
            print(f"[{timestamp()}] {self.client_address[0]} {fmt % args}")


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("AX Code-Dev GUI MVP 0.3.0")
    print(f"Open: http://{HOST}:{PORT}")
    print(f"Demo workspace: {DEMO.resolve()}")
    print(f"Profiles (outside repository): {CONFIG_FILE}")
    print(f"Claude Code CLI: {'available' if claude_status()['installed'] else 'not found'}")
    print("Note: Claude Code may transmit selected source/configuration to Anthropic or your configured provider.")
    print("No GUI telemetry · No automatic source writes · Press Ctrl+C to stop")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
