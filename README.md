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

## 사내망 Windows IP → 포트 전달 → WSL 사이트

지원하는 접속 구조는 **사내 PC의 브라우저 → Windows 사내망 IPv4:8765 → Windows portproxy → WSL2 NAT IPv4:8765 → CODEdev**입니다. Windows와 WSL이 같은 IP를 쓰는 구성이 아니며, 앱 실행 옵션만으로 Windows 포트 전달이 생성되지는 않습니다.

### 1. WSL에서 서버 실행

Windows `ipconfig`에 표시되는 **사내망 어댑터의 IPv4 주소**가 `10.20.30.40`인 예시입니다. 아래 모든 명령에서 실제 주소로 바꾸세요. 공인 IP나 WSL IP를 `--allow-host`에 넣지 않습니다.

```bash
git pull origin main
python3 app.py --host 0.0.0.0 --port 8765 --allow-host 10.20.30.40
```

`0.0.0.0`은 WSL 서버의 바인딩 주소입니다. 브라우저에는 **http://10.20.30.40:8765**를 입력합니다. 기본 `python3 app.py` 실행은 계속 localhost 전용이며, localhost 접속도 유지됩니다.

### 2. Windows에서 포트 전달 설정

**관리자 PowerShell**을 열고 저장소 폴더로 이동합니다. 저장소가 WSL에만 있다면 WSL에서 `wslpath -w "$PWD"`로 Windows 경로를 확인한 후 PowerShell에서 `Set-Location '해당 경로'`를 실행하세요. `wsl.exe -l -q`로 서버를 실행 중인 배포판 이름을 확인합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Distro Ubuntu
```

`Ubuntu`도 실제 배포판 이름으로 바꿉니다. `-ExecutionPolicy Bypass`는 이 PowerShell 프로세스에만 적용되며 시스템 실행 정책은 변경하지 않습니다.

스크립트는 다음을 순서대로 수행합니다.

1. Windows IP가 해당 PC에 할당되어 있는지 확인합니다.
2. 지정한 WSL 배포판에서 Windows IP로 향하는 경로의 source IPv4를 찾습니다. Docker/VPN 주소가 섞일 수 있는 `hostname -I`의 첫 주소를 임의로 선택하지 않습니다. 필요하면 `-WslIp 172.20.10.2`로 지정할 수 있습니다.
3. Windows IP를 Host로 사용해 WSL `/api/bootstrap`에 직접 연결합니다. 서버 미실행·바인딩 오류·Host 403을 포트 전달 전에 확인합니다. 진단 요청은 HTTP 프록시를 사용하지 않습니다.
4. IP Helper 서비스를 시작하고 **지정한 Windows IP:포트 → WSL IP:동일 포트**의 TCP 포트 전달을 생성·갱신합니다.
5. 해당 Windows IP·TCP 포트의 인바운드 방화벽 규칙을 생성·갱신합니다. **Domain/Private/Public 모두** 적용하고 `LocalSubnet`으로 제한하지 않아 사내 다른 서브넷도 허용합니다. 방화벽 전체를 끄지는 않습니다.
6. Windows IP의 `/api/bootstrap`에 다시 연결하여 전달 경로를 확인합니다. 토큰이나 소스 내용은 출력하지 않습니다.

정상 완료 시 `PASS: Windows ... -> WSL ... -> CODEdev`가 표시됩니다. 이후 같은 Windows PC와 다른 사내 PC에서 **http://10.20.30.40:8765**를 엽니다. 로컬 진단 성공만으로 다른 사내 PC에서의 접근까지 보장하지는 않으며, 회사의 중앙 방화벽/GPO/망 분리 정책에 따라 차단될 수 있습니다.

### 확인·갱신·해제

```powershell
# 현재 포트 전달/방화벽 설정과 Windows IP의 HTTP 응답 확인
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Action Status

# WSL 재시작 등으로 NAT IP가 바뀌면 Setup을 다시 실행 (동일 규칙 갱신)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Distro Ubuntu

# 이 Windows IP:포트의 전달과 스크립트가 만든 방화벽 규칙만 삭제
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Action Remove
```

포트를 바꾸면 앱의 `--port`와 스크립트의 `-Port`에 **같은 포트**를 지정합니다. Windows IP가 바뀌면 이전 IP 설정을 `Remove`로 해제하고 새 IP로 서버와 `Setup`을 실행합니다.

| 실패 지점 | 확인할 항목 |
| --- | --- |
| `WSL backend probe failed` | 해당 배포판에서 서버 실행 여부, `--host 0.0.0.0`, 동일 포트, `--allow-host`의 Windows IP, WSL 방화벽 |
| backend probe의 HTTP 403 | `--allow-host`의 Windows IP가 스크립트의 `-WindowsIp`와 일치하는지 |
| Windows endpoint probe 실패 | 기존 포트 점유, IP Helper 서비스, portproxy, Windows 유효 방화벽 정책 |
| Windows에서 PASS지만 다른 사내 PC에서 실패 | 회사 GPO·중앙 방화벽·서브넷 간 접근 정책, 클라이언트 프록시 |

이미 **mirrored 모드**를 사용하는 경우 이 NAT용 스크립트로 포트 전달을 생성하지 않습니다. Microsoft 공식 [WSL 네트워킹 안내](https://learn.microsoft.com/en-us/windows/wsl/networking)를 참고하세요.

### 앱 설정 및 접근 권한

- `--allow-host`: 브라우저 URL의 IP/호스트 이름만 지정하며 포트·URL은 제외합니다. 여러 주소는 옵션을 반복합니다. 지정한 주소와 localhost 외 요청은 차단하며 Origin·CSRF 검증도 유지합니다.
- 환경변수로도 지정 가능: `AX_HOST=0.0.0.0 AX_ALLOWED_HOSTS=10.20.30.40 python3 app.py`. 포트는 `AX_PORT` 또는 `--port`로 지정합니다 (기본 8765).
- GUI에 별도 로그인은 없습니다. 노출한 Windows IP:포트로 접근 가능한 사내 사용자는 소스 열람·변경 승인 등의 기능을 사용할 수 있습니다. `--allow-host`는 브라우저의 접속 주소 검증이며 클라이언트 IP 제한이 아닙니다.
- PowerShell 스크립트에는 Windows 관리자 권한이 필요합니다. 저장소의 파일을 내려받는 것만으로 사용자 PC 설정이 바뀌지 않습니다.

## 두 가지 사용 방법

| 경로 | 작업 방식 |
| --- | --- |
| **직접 요청** | 개발 환경 저장 → SRS, SDD, Jira 본문 또는 자유 요청 입력 → 변경안 생성 (관련 파일은 자동 탐색) |
| **에이전트 수신** | SDD 인계 또는 검증 피드백을 API로 접수 → 수신함에서 작업 확인 → 변경안 생성 또는 열기 |

두 경로 모두 **Diff 검토 → 승인·반려 → 결과 확인**을 거칩니다. 승인 전에는 소스를 수정하지 않습니다.

에이전트 연동 방법과 예시는 [docs/orchestration.md](docs/orchestration.md)를 참고하세요.

## 개발 환경

프로젝트별로 **빌드 명령어, ARCH, CROSS_COMPILE, 수정 허용·제외 경로, 코딩 규칙**을 설정하고 나중에 수정할 수 있습니다. **수정 허용 경로는 Project Root 기준 상대 경로**입니다 (예: `drivers/power/supply/**`). 허용 폴더를 먼저 탐색하며, 화면에서 탐색 후보 수·허용 파일 수·제한/누락 경로를 확인할 수 있습니다. **수정 가능한 파일이 발견되면** Code-Dev와 개발 환경 설정 화면에 파일 경로 목록이 표시됩니다. 파일명/하위 경로 검색과 더 보기를 지원하며, 탐색이 제한되었다면 목록이 일부만 포함될 수 있음을 안내합니다. 목록은 확인용으로 직접 파일을 선택할 필요가 없습니다. 파일을 별도로 지정할 필요 없이 Claude Code가 수정 허용 범위 안에서 관련 파일을 찾습니다. 기능/대상이 모호하면 파일 선택 오류 대신 개발 요청을 구체화하는 질문을 표시합니다. 빌드 명령어는 참고 정보이며 실행하지 않습니다. 설정은 `~/.config/ax-code-dev/profiles.json`에 저장됩니다.

**현재 범위:** 하나의 요청에서 기존 UTF-8 파일 최대 3개, 실제 빌드·테스트·플래싱 없음. **`editable_paths`에 매칭되는 일반 파일은 64KB를 넘어도 수정 허용 목록에 포함됩니다.** 파일 크기나 확장자에 따라 조용히 걸러내지 않습니다. Claude Code 파일 선택에도 매칭된 파일 경로를 모두 전달하며, 목록이 길면 400개 단위로 나눠 모델이 검토합니다. 파일당 64KB 이하에서는 전체 파일을 재작성하는 변경안을, 초과하면 원본과 정확히 일치하는 구간 교체 변경안을 생성합니다. 대형 파일의 실제 편집 가능성은 소스 종류와 컨텍스트에 따라 달라지며, 호스트의 텍스트 처리 상한은 8MB입니다. 심볼릭 링크와 숨김 파일/안전상 제외 폴더 등 보안 경계 및 별도 탐색 자원 한도는 유지되며 해당 제한은 화면에 표시됩니다. 수신함과 작업 이력은 서버를 재시작하면 초기화됩니다.

**보안:** Claude Code 호출 시 작업 요청, 소스 및 개발 설정이 AI 서비스로 전송될 수 있습니다. 사내 소스는 조직 정책을 확인하고, 설정에 비밀정보를 입력하지 마세요.



**Reading is not editing:** `Project Root` is the read-only source-reference boundary. `editable_paths` and `blocked_paths` limit **changes only**, not which related code can be consulted. CODEdev can read bounded excerpts of other drivers, kernel headers, Makefile/Kconfig, and related files within Project Root. The tool still passes only selected relevant references to Claude Code; it does not send or index the entire repository. Hidden/secret paths, symlinks and unsafe file types are excluded. The CLI has no shell or unrestricted filesystem tools.

## Claude Code 대화 및 실행 기록

요청 전송 후 GUI에서 **Claude Code 호출 상태, 관련 파일, 사용자 요청, Claude Code에 전달한 작업 지시(소스 원문 제외), 실제 Claude Code 응답 및 판단 근거, 실패 사유**를 확인할 수 있습니다. CLI 호출 성공과 코드 변경 유무를 별도 표시합니다. **변경 없음**은 호출 실패가 아니며, Claude Code가 반환한 설명을 확인하고 요청을 수정해 다시 보낼 수 있습니다. 이때 승인·반영은 불가능하며 원본 파일은 유지됩니다. 원시 JSON·소스 원문·내부 추론은 대화창에 표시하지 않습니다. 여러 파일의 변경안은 Diff에서 파일별로 확인한 뒤 일괄 승인합니다. 기록은 서버 메모리에만 보관되며 재시작 시 사라집니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

Windows 포트 전달 스크립트의 설정·갱신·해제 흐름은 Windows 네트워크 명령을 모킹하여 검증합니다 (PowerShell 7+, 실제 네트워크 설정 변경 없음).

```powershell
pwsh -NoProfile -File tests/test_wsl_port_forward.ps1
```

### Claude Code response timeout

The Claude Code CLI is monitored by **response activity**, not by an absolute
execution time limit. Once real `assistant` or `stream_event` data is received,
each subsequent event renews the 180-second idle window. Long-running requests
may therefore continue for longer than 180 seconds when Claude is still
responding. If Claude never begins responding, or stops producing response
events for 180 seconds, CODEdev stops the stalled subprocess and records an
error. Merely starting the CLI does not count as a model response.

