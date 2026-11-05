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

## WSL에서 Windows IP로 접속

기본 실행은 localhost 전용입니다. Windows의 LAN IPv4 주소가 `192.168.1.50`이라면 WSL에서 다음과 같이 실행합니다. 주소는 Windows `ipconfig`의 실제 IPv4 주소로 바꾸세요.

```bash
python3 app.py --host 0.0.0.0 --allow-host 192.168.1.50
```

접속 주소: **http://192.168.1.50:8765** (`0.0.0.0`은 서버 바인딩 주소이며 브라우저 접속 주소가 아닙니다). localhost 접속도 계속 지원합니다. 화면의 서버 상태에는 실제 접속 주소가 표시됩니다.

- `--port 9000`: 포트 변경 (기본값: `AX_PORT` 또는 8765).
- `--allow-host`: 접속에 사용할 IP/호스트 이름만 지정, 포트·URL 제외. 여러 주소는 옵션을 반복합니다.
- 환경변수로도 지정 가능: `AX_HOST=0.0.0.0 AX_ALLOWED_HOSTS=192.168.1.50,dev-pc python3 app.py`.
- 기본 localhost 외에는 지정한 바인딩 주소와 허용 호스트만 받습니다. 와일드카드 호스트 허용은 지원하지 않으며 Origin과 CSRF 검증도 유지합니다.

**WSL2 기본 NAT 모드:** 앱 설정 외에 Windows 포트 전달이 필요합니다. **관리자 PowerShell**에서 실행하세요. `Ubuntu`는 `wsl -l -q`에 표시되는 실제 배포판 이름으로, Windows IP와 포트도 실행 설정에 맞게 바꿉니다.

```powershell
$Distro = "Ubuntu"
$WindowsIp = "192.168.1.50"
$Port = 8765
$WslIp = ((wsl.exe -d $Distro hostname -I).Trim() -split '\s+')[0]
netsh interface portproxy add v4tov4 listenaddress=$WindowsIp listenport=$Port connectaddress=$WslIp connectport=$Port
New-NetFirewallRule -Name "CODEdev-$Port" -DisplayName "CODEdev $Port" -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $WindowsIp -LocalPort $Port -RemoteAddress LocalSubnet -Profile Private
```

`hostname -I`에 여러 IP가 나오면 실제 WSL NAT 어댑터의 IPv4 주소를 `$WslIp`로 지정하세요. WSL 재시작으로 IP가 바뀌면 포트 전달 명령을 다시 실행합니다. 방화벽 규칙은 처음 한 번만 추가하며, 다른 기기에서는 Windows 네트워크가 Private인지 확인하세요. Windows IP가 바뀌면 앱의 `--allow-host`와 Windows 설정도 갱신합니다.

설정 확인 및 해제 (관리자 PowerShell, 위 변수 사용):

```powershell
netsh interface portproxy show v4tov4
Test-NetConnection $WindowsIp -Port $Port
# 접속 허용을 끝낼 때만 실행
netsh interface portproxy delete v4tov4 listenaddress=$WindowsIp listenport=$Port
Remove-NetFirewallRule -Name "CODEdev-$Port"
```

**이미 mirrored 모드를 사용하는 경우:** NAT용 portproxy는 필요하지 않습니다. Windows/Hyper-V 방화벽에서 해당 포트를 허용해야 할 수 있습니다. Microsoft 공식 [WSL 네트워킹 안내](https://learn.microsoft.com/en-us/windows/wsl/networking)를 참고하세요.

**네트워크 접근 권한:** GUI에는 별도 로그인 인증이 없습니다. 접속 가능한 사용자는 소스 열람·변경 승인 등 로컬 사용자와 같은 작업을 할 수 있으므로 신뢰하는 네트워크에서만 사용하세요. `--allow-host`는 접속 URL 검증이며 클라이언트 IP 접근제어가 아닙니다. 인터넷 공유기 포트 개방은 하지 마세요.

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

### Claude Code response timeout

The Claude Code CLI is monitored by **response activity**, not by an absolute
execution time limit. Once real `assistant` or `stream_event` data is received,
each subsequent event renews the 180-second idle window. Long-running requests
may therefore continue for longer than 180 seconds when Claude is still
responding. If Claude never begins responding, or stops producing response
events for 180 seconds, CODEdev stops the stalled subprocess and records an
error. Merely starting the CLI does not count as a model response.

