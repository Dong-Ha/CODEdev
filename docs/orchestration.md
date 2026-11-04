# AX 오케스트레이션 연동

Code-Dev는 **SRS/SDD 인계**와 **검증 실패 재작업**을 동일한 작업 계약으로 받습니다. Claude Code가 생성한 제안은 로컬 GUI에서 검토하며, **자동 생성(`auto_generate`)은 자동 승인/적용이 아닙니다.**

## 설정

코드 개발 GUI를 실행하는 **같은 Linux/WSL 호스트**에서 고엔트로피 토큰을 환경변수로 지정합니다. 토큰은 파일이나 저장소에 커밋하지 마세요.

```bash
export AX_AGENT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 app.py
```

호출하는 상위 에이전트 프로세스는 위 토큰을 안전하게 전달받아야 합니다. GUI는 `127.0.0.1`에만 바인딩하며, 별도 외부 네트워크 공개 기능은 없습니다.

## 작업 접수 API

`POST http://127.0.0.1:8765/api/agent/handoffs`

Header: `Content-Type: application/json`, `X-AX-Agent-Token: <설정한 토큰>`

```json
{
  "workspace": "/home/user/repos/linux",
  "source_agent": "SW Design",
  "source_kind": "sdd",
  "source_ref": "SDD-IFPMIC-014",
  "source_content": "설계 명세에서 필요한 관련 본문과 수용 조건",
  "instruction": "SDD의 입력 전류 검증 조건을 구현한다.",
  "upstream_run_id": "ax-run-014",
  "auto_generate": false
}
```

| 필드 | 설명 |
| --- | --- |
| `workspace` | **필수**. 미리 설정한 프로젝트 경로 |
| `target` | **선택**. 생략하면 수정 허용 범위에서 자동 선택. 지정 시 허용 경로 내 단일 파일 |
| `source_agent` | **필수**. 호출 에이전트 이름(SW Design, SQE 등) |
| `source_kind` | `sdd`, `srs`, `jira`, `verification`, `freeform` 중 하나 |
| `source_ref` | 추적용 문서/이슈 ID 또는 URL. **URL은 조회하지 않음** |
| `source_content` | 원문 중 필요한 부분. 12,000자 이하. Claude Code에 전송됨 |
| `instruction` | **필수**, 5~4,000자. 이번 변경 요청 |
| `upstream_run_id` | 이전 작업/검증 실행 ID |
| `auto_generate` | 기본 `false`. `true`이면 변경안까지 자동 생성하되, 승인 전에는 소스 미수정 |

반환 HTTP `202`와 `task.id`, `task.status`를 저장해 작업을 추적하세요. `auto_generate=true`에서 생성 실패 시에도 작업은 `failed` 상태로 남으며 GUI에서 재시도할 수 있습니다.

## 상태 조회

`GET /api/agent/handoffs/{task.id}` 또는 `GET /api/agent/handoffs` — 같은 토큰 필요

| 상태 | 의미 |
| --- | --- |
| `queued` | 작업 수신, 아직 코드 제안 없음 |
| `generating` | Claude Code 작업 생성 중 |
| `review` | Diff 검토 및 승인 대기 |
| `no_change` | Claude Code 호출 정상 완료, 현재 파일과 반환 코드 동일. 승인할 변경 없음 |
| `failed` | 변경안 생성 실패, 수신함에서 재시도 가능 |
| `applied` | 사람이 승인하여 파일 반영 |
| `rejected` | 제안 반려 |
| `undone` | 이전에 적용한 변경을 되돌림 |

GUI의 **에이전트 수신함**에서 작업을 선택해 생성/검토할 수 있습니다. 프로젝트의 개발 환경 설정을 변경한 경우 이전 설정으로 만든 제안은 적용되지 않습니다.

`target`이 없는 경우 Claude Code는 허용된 파일의 경로 목록으로 하나를 선택합니다. 경로가 모호하거나 후보가 너무 많으면 파일 지정을 요청하며 임의로 수정하지 않습니다. 승인 전에는 코드가 바뀌지 않습니다.

## 현재 제약 및 보안

- 서버는 단일 머신 `localhost` 사용을 전제로 합니다. 멀티호스트 오케스트레이션, 사용자별 권한, 영구 큐는 아직 없습니다.
- 작업과 이력은 **메모리 보관**이며 재시작하면 사라집니다. 작업 ID와 상태를 상위 오케스트레이터에서도 관리해야 합니다.
- 수정 허용 경로 제한, 원본 SHA-256 확인, 명시적 사람 승인 절차는 두 진입 경로 모두 같습니다.
- 원문/설정이 Claude Code의 구성된 AI 서비스로 전송될 수 있습니다. 인증 토큰을 URL/로그/문서에 남기지 마세요.

## 실행 기록 및 결과 구분 (v0.8)

The GUI uses asynchronous jobs so users can inspect real CLI progress while a
proposal is running. A handoff can use `POST /api/jobs/handoff` with `{"id":"..."}`
and the browser can use `POST /api/jobs` with the normal human request payload.
Both require the local GUI CSRF token; orchestration intake still uses its
independent `X-AX-Agent-Token`.

| API | Purpose |
| --- | --- |
| `POST /api/jobs` | Start a human request and return job ID immediately |
| `POST /api/jobs/handoff` | Generate an existing agent handoff asynchronously |
| `GET /api/jobs` | List recent in-memory jobs (localhost) |
| `GET /api/jobs/{id}` | Poll status, phase, visible messages, errors, proposal ID |

Jobs have `queued`, `running`, `complete`, `no_change`, or `failed` status and a distinct
`phase`, plus `cli_status` (`not_started`, `running`, `succeeded`, `failed`).
`no_change`는 **CLI 호출 성공 후 원본과 수정 결과가 같은 경우**이며, 구조화된 `summary`, `rationale`, `risk`, `checks`와 대상 파일을 조회할 수 있지만 실제 코드 적용은 허용되지 않습니다.
`failed`는 실행 오류·형식 오류 등으로 작업이 완료되지 못한 상태입니다. Events distinguish submitted user instructions, CLI progress, visible
Claude Code structured response summaries, and errors. Raw source, raw CLI
JSON, tool internals, and hidden reasoning are intentionally omitted from the
conversation UI. The structured change proposal remains in the Diff/Review
panel. Jobs do not persist after server restart. Existing synchronous APIs are
kept for compatibility. `auto_generate=true` handoffs are also traced.
