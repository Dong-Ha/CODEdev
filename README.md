# AX Code-Dev Request Studio

개발 환경·빌드 방법·수정 가능한 파일을 정의하고, **SDD / Jira / 자유 요청 / 다른 AX 에이전트의 요청을 향후 code-dev agent에 전달할 형태로 접수**하는 웹 도구입니다.

**code-dev agent 자체는 아직 구현하지 않습니다.** 현재 버전은 저장된 요청과 개발 환경을 **Claude Code CLI로 바로 전달하고 텍스트 응답을 수신**할 수 있습니다. 소스 본문 읽기·파일 수정·빌드는 실행하지 않습니다. CLI가 없어도 환경 저장과 접수만 하기는 사용할 수 있습니다.

## 실행

서버는 Python 3.9+ 표준 라이브러리만 필요합니다. 바로 전달 기능은 서버와 같은 WSL/Linux 사용자 환경에 설치·인증된 Claude Code CLI가 필요합니다.

```bash
git clone https://github.com/Dong-Ha/CODEdev.git
cd CODEdev
claude auth status  # 바로 전달을 사용할 경우 확인; 미인증이면 claude auth login
python3 app.py
```

기존 설치는 `git pull origin main` 후 서버를 재시작합니다. Windows 브라우저에서 **http://127.0.0.1:8765**로 접속합니다.

## 사용 흐름

1. **개발 환경**: WSL/Linux 서버 기준 Project Root를 연결합니다. 프로젝트명, 개발 환경 정보, 대상 OS·보드·커널, 빌드 폴더/명령어/환경변수를 저장합니다.
2. **수정 파일 지정**: 개별 파일(예: `drivers/power/supply/s2mf301_charger.c`) 또는 폴더 패턴(예: `include/linux/power/**`)을 한 줄씩 입력합니다. 제외 경로가 우선하며, 저장된 설정의 실제 파일 목록을 검색해서 확인합니다. 빌드 명령은 기록만 합니다.
3. **요청 작성**: SDD·Jira·SRS·검증 피드백·자유 요청을 선택하고 요청, 참고 본문, 출처 ID를 입력합니다. **URL이나 Jira 이슈를 자동 조회하지 않습니다.**
4. **Claude Code로 바로 전달**: 요청과 당시 환경/허용 파일 목록을 저장하고, 이를 담은 프롬프트를 CLI stdin에 전달합니다. **접수만 하기**를 선택하면 전송하지 않습니다.
5. **응답 확인**: 접수 내역에서 실제 전달 프롬프트, 실행 상태, Claude 응답/오류와 이전 전송 결과를 확인합니다. 기존 접수 건도 **Claude Code로 전달** 버튼으로 보낼 수 있습니다. JSON 내보내기도 유지합니다.

다른 에이전트의 요청도 동일한 접수 내역에 나타나며 출처와 상위 실행 ID를 유지합니다. API 예시는 [오케스트레이션 계약](docs/orchestration.md)을 참고하세요.

## Claude CLI 연결 범위

- 모델과 인증은 서버 사용자의 기존 Claude CLI 설정을 사용합니다. 별도 API 키 입력창은 없습니다. 설치 감지는 인증 성공을 뜻하지 않으며 인증/실행 실패는 요청 상세에 표시됩니다.
- 요청·참고 본문·환경 설정·파일 경로는 CLI에 구성된 AI 서비스로 전송됩니다. 소스 파일 본문은 포함하지 않습니다. 원문이 필요하면 Claude가 추가 정보를 요청할 수 있습니다.
- CLI는 임시 폴더에서 `claude -p`의 stream-json 출력으로 실행합니다. 내장 도구, MCP 도구와 사용자 hook 실행을 제한하고, 기존 레거시 code-dev 프롬프트/JSON 변경안 스키마를 사용하지 않습니다. 명령어는 셸을 거치지 않습니다.
- 서버당 최대 3건, 프로젝트당 1건을 실행하며 요청당 최대 5회 전송 기록을 보관합니다. 실제 모델 이벤트가 180초 동안 없으면 중단하고 실패로 표시합니다. 활발한 응답에는 총 180초 제한을 적용하지 않습니다.
- 실행 상태·프롬프트·응답은 requests.json에 보관합니다. 재시작 당시 진행 중이던 실행은 `cli_interrupted`로 표시하며 자동 재전송하지 않습니다. 필요하면 상세 화면에서 명시적으로 다시 전달하세요.
- `waiting_for_agent`는 접수만 한 요청, `cli_queued`/`cli_running`은 CLI 실행 중, `cli_complete`는 응답 수신 완료, `cli_failed`는 호출/응답 실패입니다. `cli_complete`는 코드 개발/빌드 성공이 아닙니다.
- 현재 기능은 독립 요청의 프롬프트 전달입니다. 다중 턴 대화·소스 자동 읽기·수정·build 실행을 담당할 code-dev agent는 후속 구현입니다.

CLI 플래그는 [Claude Code 공식 CLI 문서](https://code.claude.com/docs/en/cli-reference)를 따릅니다.

## 설정과 요청 보관

- 개발 환경: `~/.config/ax-code-dev/profiles.json` (`AX_CONFIG_FILE`로 변경).
- 요청과 환경 스냅샷: 설정 파일과 같은 폴더의 `requests.json` (`AX_REQUESTS_FILE`로 변경).
- 요청은 서버 재시작 후에도 유지됩니다. 파일은 소스 저장소 밖에 원자적으로 저장되며 권한은 `0600`입니다. 한 서버 프로세스에서 사용하세요. 여러 프로세스가 같은 저장 파일을 공유하는 구성은 지원하지 않습니다.
- 요청 보관 상한은 200개 / 64MB입니다. 한도 도달 시 오래된 요청을 임의로 삭제하지 않고 접수를 거절합니다. 필요한 경우 서버를 중지하고 요청 파일을 백업·정리하세요.
- 환경을 수정해도 과거 요청의 스냅샷은 바뀌지 않습니다. UI에 **환경 변경 · 재접수 필요**가 표시되고, 에이전트의 상세 조회는 409로 차단됩니다. 요청을 다시 작성해 현재 설정으로 접수하세요.
- 접수 때의 파일 목록은 파일 경로·크기만 포함합니다. 소스 내용은 읽거나 복사하지 않습니다. 향후 실행기는 현재 환경 revision, 실제 경로/심볼릭 링크, 파일 내용/버전과 수정 권한을 다시 확인해야 합니다.
- 숨김 파일, 심볼릭 링크, 빌드/출력 폴더 등 기존 탐색 제외 규칙을 유지합니다. 탐색 상한에 걸리거나 허용 파일이 없으면 접수를 차단하고 경로 수정을 안내합니다. 일부 경로가 없으면 탐색 경고에 표시됩니다.

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
- GUI에 별도 로그인은 없습니다. 노출한 Windows IP:포트로 접근 가능한 사내 사용자는 환경·요청 열람 및 접수·Claude CLI 호출 기능 (기존 Claude 모드 활성화 시 소스 열람·변경 승인 기능)을 사용할 수 있습니다. `--allow-host`는 브라우저의 접속 주소 검증이며 클라이언트 IP 제한이 아닙니다.
- PowerShell 스크립트에는 Windows 관리자 권한이 필요합니다. 저장소의 파일을 내려받는 것만으로 사용자 PC 설정이 바뀌지 않습니다.

## 기존 Claude 프로토타입

이전 변경안 생성/승인 UI와 API는 기본 실행에서 비활성화됩니다. 기존 실험을 재현해야 할 때만 명시적으로 활성화하세요.

```bash
AX_ENABLE_LEGACY_CLAUDE=1 python3 app.py
# http://127.0.0.1:8765/legacy
```

이 모드는 별도의 예전 프로토타입이며 이번 code-dev agent 구현에 해당하지 않습니다. 설치·인증된 Claude CLI가 필요하고, 요청/소스/환경이 설정된 AI 서비스로 전송될 수 있습니다. 빌드는 실행하지 않으며 파일 적용에는 사람 승인이 필요합니다. 기존 `/api/agent/handoffs`, `/api/jobs`, Diff/승인 흐름은 이 모드에서만 예전 동작을 유지합니다. 기존 이력은 메모리 보관입니다. 기본 접수 API(`/api/requests`, `/api/agent/requests`)는 이 모드에서도 모델을 실행하지 않습니다.

`agents/code-dev.md`는 이 레거시 프로토타입의 프롬프트입니다. 새 에이전트와의 연결 경계는 [오케스트레이션 계약](docs/orchestration.md)에 정의되어 있습니다.

## 검증

```bash
python3 -m unittest discover -s tests -v
node --check web/intake.js
node --check web/app.js
```

테스트는 기본 접수·영구 저장·환경 스냅샷·중복 접수/실행 방지·인증·모의 CLI 프로세스 전달/응답/실패·기존 프로토타입을 검증합니다. 실제 모델/하드웨어/빌드는 실행하지 않습니다.

선택적인 DOM/HTTP 통합 테스트는 `tests/test_intake_dom.cjs`입니다. 별도 테스트 환경에 `jsdom`을 설치하고 임시 `AX_CONFIG_FILE`을 사용하는 서버를 실행한 뒤 테스트 파일의 실행 안내를 따르세요. 이 테스트는 환경 저장, 요청 접수, 중복 방지, 페이지 재접속, 과거 스냅샷을 확인하며 브라우저 렌더링 검증을 대신하지 않습니다.

Windows 포트 전달 스크립트는 PowerShell 7+ 환경에서 네트워크 명령을 모킹해 검증할 수 있습니다.

```powershell
pwsh -NoProfile -File tests/test_wsl_port_forward.ps1
```
