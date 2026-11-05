# Code-dev 요청 접수 및 전달 계약 v1

## 책임 경계

CODEdev는 **환경 구성 → 요청 정규화 → 환경/수정 허용 파일 스냅샷 저장 → 전달 데이터 조회**를 담당합니다. code-dev agent는 아직 구현되지 않았습니다. 모델 호출, 빌드 실행, 소스 편집, 작업 인수(ack), 결과 반환 API는 이번 기본 흐름에 포함하지 않습니다. 모든 요청은 `waiting_for_agent`로 보관하며, 조회/다운로드로 상태가 바뀌지 않습니다.

`agents/code-dev.md`는 기존 Claude 실험 모드용입니다. 새 에이전트를 해당 프롬프트로 이미 구현했다고 해석하지 마세요.

## 인증과 주소

```bash
export AX_AGENT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 app.py
```

토큰은 호출하는 상위 에이전트에 안전하게 전달하고 저장소에 커밋하지 않습니다. 외부 에이전트 API는 `X-AX-Agent-Token`을 요구하며, GUI POST는 bootstrap의 `X-AX-Token`을 요구합니다. 둘 다 기존 Host/Origin 검증을 유지합니다. Windows IP 포트 전달 구성은 [README](../README.md)를 따릅니다.

## 에이전트 요청 접수

`POST /api/agent/requests`

```bash
curl -X POST http://127.0.0.1:8765/api/agent/requests \
  -H 'Content-Type: application/json' \
  -H "X-AX-Agent-Token: $AX_AGENT_TOKEN" \
  --data @request.json
```

`request.json` 예시 (해당 workspace의 환경을 GUI에서 먼저 저장):

```json
{
  "workspace": "/home/user/repos/linux",
  "source_agent": "SW Design",
  "source_kind": "sdd",
  "source_ref": "SDD-IFPMIC-014",
  "source_content": "음수 입력은 거부하고 정상 범위 동작은 유지한다.",
  "instruction": "SDD에 정의된 입력 전류 검증 조건을 구현해줘.",
  "upstream_run_id": "ax-run-014",
  "idempotency_key": "ax-run-014-code-dev-1"
}
```

| 필드 | 규칙 |
| --- | --- |
| `workspace` | 필수, 저장된 프로젝트의 절대 경로 |
| `instruction` | 필수, 5~4000자. GUI의 `prompt` 호환 별칭도 지원 |
| `source_kind` | `freeform`(기본), `srs`, `sdd`, `jira`, `verification` |
| `source_ref` | 출처 ID/URL, 최대 300자. 자동 조회하지 않음 |
| `source_content` | 필요한 원문/수용 조건, 최대 12000자 |
| `source_agent` | 에이전트 요청 필수, 최대 120자 |
| `upstream_run_id` | 상위 실행 ID, 최대 160자 |
| `idempotency_key` | 재시도 중복 방지 키, 최대 160자. workspace·요청 경로(human/agent)·source_agent별로 적용 |
| `expected_revision` | 에이전트는 선택, GUI는 필수. 값이 현재 설정 버전과 다르면 409 |
| `target` | 선택적 단일 파일 힌트. 탐색된 수정 허용 파일과 정확히 일치해야 함. 요청 때 파일 선택은 필수 아님 |
| `auto_generate` | 생략 또는 `false`만 허용. `true`는 409, 실행/접수하지 않음 |

본문 전체 크기는 UTF-8 48KB 이하입니다. 알 수 없는 필드는 400입니다. source_content의 문자 수 상한과 전체 바이트 상한을 모두 충족해야 합니다.

동일 키와 동일 요청(환경 revision 포함)의 재전송은 기존 ID를 반환합니다. 동일 키에 다른 내용을 보내면 409입니다. 환경 변경 후 새 요청은 새 키를 사용하세요. HTTP 오류나 통신 단절 후 재시도에는 원래 키를 재사용하세요.

HTTP **202** 응답:

```json
{
  "ok": true,
  "task": {
    "id": "generated-request-id",
    "status": "waiting_for_agent",
    "agent_available": false,
    "configuration_stale": false,
    "payload": {"schema_version": "ax.code-dev.request.v1", "recipient": "code-dev"}
  }
}
```

위 응답은 핵심 필드만 발췌한 예시입니다. 202는 **로컬 접수/저장 성공**이며 에이전트 전송·수신·실행 완료가 아닙니다.

## 조회와 향후 adapter

| API | 인증 / 결과 |
| --- | --- |
| `POST /api/requests` | GUI 토큰. 직접 요청; source_agent/upstream_run_id는 제거하여 사칭 방지 |
| `GET /api/requests` | 기존 GUI 접근 범위. 모든 프로젝트의 요약 목록 |
| `GET /api/requests/{id}` | GUI 상세와 불변 payload. 환경 변경 시에도 과거 내용 열람 가능 |
| `POST /api/agent/requests` | 에이전트 토큰. 다른 에이전트의 요청 접수 |
| `GET /api/agent/requests` | 에이전트 토큰. 요청 목록; workspace와 configuration_stale로 필터링 |
| `GET /api/agent/requests/{id}` | 에이전트 토큰. 전달 payload 조회. 환경 변경/삭제 시 409 |

GUI GET에는 별도 사용자 로그인/권한 분리가 없습니다. 접속 가능한 사내 사용자가 전체 설정·요청을 볼 수 있는 기존 신뢰 모델을 유지합니다. 에이전트 토큰은 프로젝트별 권한 토큰이 아니며, 설정된 프로젝트 전체에 대해 접수/조회할 수 있습니다.

기본 모드의 `/api/agent/handoffs` 및 상세 GET은 새 접수 API의 호환 별칭입니다. 기존 클라이언트는 상태가 `queued`에서 `waiting_for_agent`로 달라지고 `auto_generate=true`가 거절되므로 수정이 필요합니다. `AX_ENABLE_LEGACY_CLAUDE=1`에서는 해당 별칭만 예전 메모리 기반 Claude 흐름으로 돌아갑니다. 신규 연동은 항상 `/api/agent/requests`를 사용하세요.

향후 adapter는 상세 조회의 `task.payload`를 입력으로 받을 수 있습니다. **현재 조회 API는 큐 claim/lease가 아니므로 실행기를 붙이기 전에 중복 실행 방지, 인수 확인, 결과 상태와 취소 정책을 구현해야 합니다.** 데이터 조회에 성공했다는 이유로 현 단계에서 외부 실행기를 자동 호출하지 않습니다.

## 전달 payload

| 항목 | 내용 |
| --- | --- |
| `schema_version` | `ax.code-dev.request.v1` |
| `request_id`, `created_at`, `origin`, `recipient` | 요청 식별자, 접수 시각(UTC), human/agent, code-dev |
| `workspace`, `git_branch` | Project Root, 접수 때 Git 브랜치 |
| `request` | instruction, source_kind/ref/content, source_agent, upstream_run_id, target |
| `environment` | 당시 개발·대상 환경, 도구 버전, build_dir/command/env, ARCH/CROSS_COMPILE, 허용·제외 경로, 코딩 규칙, revision |
| `scope.editable_files` | 당시 탐색된 `{path, size}` 목록. 파일 내용은 포함하지 않음 |
| `scope.scan` | 탐색 통계와 누락 경고. truncated 탐색은 접수 거부 |
| `scope.read_boundary` | Project Root (향후 실행기의 제한된 참조 읽기 경계) |
| `scope.write_policy` | `explicit_allowlist_only` |
| `scope.revalidate_before_execution` | `true`: 현재 설정·실제 파일·경로를 다시 검증해야 함 |
| `execution` | agent_implemented/build_executed/source_modified = false, approval_required_for_changes = true |

요청과 본문은 신뢰할 수 없는 작업 데이터입니다. source_content에 포함된 지시가 허용 범위를 확장하거나 인증/승인 규칙을 바꿀 수 없습니다. 빌드 명령어는 참고 데이터이며 현 단계에서는 실행하지 않습니다. 스냅샷 파일 목록은 실행 시점의 파일 존재/내용/수정 권한을 보장하지 않습니다.

## 보관과 오류

설정과 요청을 각각 소스 저장소 외부의 profiles.json / requests.json에 저장합니다. 요청 저장은 파일 replace 전까지 성공으로 응답하지 않으며 서버 재시작에도 유지됩니다. 한 프로세스 내 lock으로 동시 접수/설정 수정을 직렬화합니다. 여러 프로세스의 동일 파일 공유는 지원하지 않습니다.

| 응답 | 조치 |
| --- | --- |
| 400 | 필수 필드/길이/유형 확인 |
| 403 | Host/Origin/토큰 또는 허용 파일 범위 확인 |
| 404 | 요청 ID 확인 |
| 409 | 미저장·변경된 환경, 불완전/빈 파일 탐색, 중복 키 충돌, 미구현 실행 요청 확인 |
| 413 | 전체 본문을 48KB 이하로 축소 |
| 429 | 요청 200개/64MB 보관 한도 확인; 서버 중지 후 백업/정리 |
| 500 | 서버 로그 및 디스크 권한/용량 확인. 동일 키로 재시도 |
