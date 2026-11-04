# AX Code-Dev Studio

**Claude Code CLI 기반 코드 변경 검토 GUI**입니다. 사람이 직접 요청하거나 AX 에이전트의 작업을 받아, 변경안을 확인하고 승인한 뒤에만 코드를 수정합니다.

## 실행

Python 3.9+와 같은 WSL/Linux 환경에 설치·인증된 Claude Code CLI가 필요합니다.

```bash
git clone https://github.com/Dong-Ha/CODEdev.git
cd CODEdev
claude auth status
python3 app.py
```

Windows 브라우저: **http://127.0.0.1:8765**

## 두 가지 사용 방법

| 경로 | 작업 방식 |
| --- | --- |
| **직접 요청** | 개발 환경 저장 → SRS, SDD, Jira 본문 또는 자유 요청 입력 → 변경안 생성 (관련 파일은 자동 탐색) |
| **에이전트 수신** | SDD 인계 또는 검증 피드백을 API로 접수 → 수신함에서 작업 확인 → 변경안 생성 또는 열기 |

두 경로 모두 **Diff 검토 → 승인·반려 → 결과 확인**을 거칩니다. 승인 전에는 소스를 수정하지 않습니다.

에이전트 연동 방법과 예시는 [docs/orchestration.md](docs/orchestration.md)를 참고하세요.

## 개발 환경

프로젝트별로 **빌드 명령어, ARCH, CROSS_COMPILE, 수정 허용·제외 경로, 코딩 규칙**을 설정하고 나중에 수정할 수 있습니다. **수정 허용 경로는 Project Root 기준 상대 경로**입니다 (예: `drivers/power/supply/**`). 허용 폴더를 먼저 탐색하며, 화면에서 탐색 후보 수·허용 파일 수·제한/누락 경로를 확인할 수 있습니다. 파일을 별도로 지정할 필요 없이 Claude Code가 수정 허용 범위 안에서 관련 파일을 찾습니다. 기능/대상이 모호하면 파일 선택 오류 대신 개발 요청을 구체화하는 질문을 표시합니다. 빌드 명령어는 참고 정보이며 실행하지 않습니다. 설정은 `~/.config/ax-code-dev/profiles.json`에 저장됩니다.

**현재 범위:** 하나의 요청에서 기존 UTF-8 파일 최대 3개(파일당 64KB), 실제 빌드·테스트·플래싱 없음. 수신함과 작업 이력은 서버를 재시작하면 초기화됩니다.

**보안:** Claude Code 호출 시 작업 요청, 소스 및 개발 설정이 AI 서비스로 전송될 수 있습니다. 사내 소스는 조직 정책을 확인하고, 설정에 비밀정보를 입력하지 마세요.



**Reading is not editing:** `Project Root` is the read-only source-reference boundary. `editable_paths` and `blocked_paths` limit **changes only**, not which related code can be consulted. CODEdev can read bounded excerpts of other drivers, kernel headers, Makefile/Kconfig, and related files within Project Root. The tool still passes only selected relevant references to Claude Code; it does not send or index the entire repository. Hidden/secret paths, symlinks and unsafe file types are excluded. The CLI has no shell or unrestricted filesystem tools.

## Claude Code 대화 및 실행 기록

요청 전송 후 GUI에서 **Claude Code 호출 상태, 관련 파일, 사용자 요청, Claude Code에 전달한 작업 지시(소스 원문 제외), 실제 Claude Code 응답 및 판단 근거, 실패 사유**를 확인할 수 있습니다. CLI 호출 성공과 코드 변경 유무를 별도 표시합니다. **변경 없음**은 호출 실패가 아니며, Claude Code가 반환한 설명을 확인하고 요청을 수정해 다시 보낼 수 있습니다. 이때 승인·반영은 불가능하며 원본 파일은 유지됩니다. 원시 JSON·소스 원문·내부 추론은 대화창에 표시하지 않습니다. 여러 파일의 변경안은 Diff에서 파일별로 확인한 뒤 일괄 승인합니다. 기록은 서버 메모리에만 보관되며 재시작 시 사라집니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

### Claude Code response timeout

The Claude Code CLI is monitored by **response activity**, not by an absolute
execution time limit. Once real `assistant` or `stream_event` data is received,
each subsequent event renews the 180-second idle window. Long-running requests
may therefore continue for longer than 180 seconds when Claude is still
responding. If Claude never begins responding, or stops producing response
events for 180 seconds, CODEdev stops the stalled subprocess and records an
error. Merely starting the CLI does not count as a model response.

