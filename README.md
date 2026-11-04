# AX Code-Dev Studio — Claude Code CLI GUI MVP v0.3

AX 워크플로우의 **Code-Dev (코드 생성·수정)** 단계에 사용하는 로컬 웹 GUI입니다. **프로젝트별 개발 환경을 처음 설정한 후 언제든 수정**할 수 있습니다. GUI는 요구사항을 Claude Code CLI에 전달하여 **변경안만 생성**하고, Diff와 체크리스트를 보여준 뒤 사용자가 승인할 때만 로컬 소스를 수정합니다. 실제 빌드·테스트·플래싱은 수행하지 않습니다.

## 1. 설치 및 실행 (Windows + WSL)

요구 사항: Python 3.9+, 웹 브라우저, 실제 AI 제안용 **Claude Code CLI** (`claude`). Python 웹 서버는 별도 패키지를 설치하지 않습니다.

```bash
git clone https://github.com/Dong-Ha/CODEdev.git
cd CODEdev

# 서버와 같은 WSL/Linux 환경에 설치된 Claude Code를 사용합니다.
claude --version
claude auth status
# 아직 인증하지 않았다면: claude auth login

python3 app.py
```

Windows 브라우저: `http://127.0.0.1:8765`

```bash
# 포트 및 프로필 경로 변경 (선택)
AX_PORT=8766 python3 app.py
AX_CONFIG_FILE="$HOME/.config/ax-code-dev/profiles.json" python3 app.py
```

`claude`가 WSL/Linux의 PATH에 있어야 합니다. Windows에만 설치된 CLI는 WSL Python 프로세스에서 자동으로 인식되지 않습니다. 인증과 모델 선택은 **Claude Code의 기존 CLI 설정**을 따르며 GUI에서 비밀번호·토큰·모델을 관리하지 않습니다. 설치 및 인증은 공식 [Claude Code 문서](https://code.claude.com/docs/en/overview)를 참고하세요.

## 2. 최초 설정과 반복 작업

1. 최초 실행 시 **Development Environment** 페이지가 열립니다. 프로젝트 경로를 입력하고 **경로 연결**을 누릅니다. 경로는 서버가 실행되는 WSL/Linux 기준입니다.
2. 프로젝트 이름·유형(Linux Kernel / 일반 프로젝트)을 설정합니다.
3. 빌드 작업 디렉터리, `ARCH`, `CROSS_COMPILE`, **빌드 명령어**, 추가 환경변수를 입력합니다. **실제 실행하는 명령이 아니라 에이전트 참고 문맥**으로만 사용합니다.
4. 수정 허용/제외 경로 패턴, 변경 목적, 코딩 지침을 입력하고 저장합니다.
5. **Code-Dev** 페이지에서 파일 1개와 요구사항을 선택합니다. **Claude Code** 또는 예제용 **Demo**를 선택한 뒤 변경안을 생성합니다.
6. **Unified Diff**와 검토 체크리스트를 확인한 뒤 명시적으로 승인해야 파일에 반영됩니다. 반려·되돌리기도 가능합니다.
7. 개발 환경을 수정하려면 언제든 **개발 환경** 페이지를 열어 재저장합니다. 이전 프로필로 만든 미승인 제안은 서버에서 승인할 수 없게 됩니다.

예시 드라이버 설정:

```text
Project root    /home/user/repos/linux
Build directory .
ARCH            arm64
CROSS_COMPILE   aarch64-linux-gnu-
Build command   make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image dtbs modules
Editable paths  drivers/power/supply/**
                include/linux/power/**
Excluded paths  **/*.key
                **/secrets/**
Change targets  charger 입력 전류 제한, 오류 반환 처리
Coding rules    기존 커널 스타일, IRQ·locking·probe 영향 확인
```

수정 허용 경로와 제외 경로는 **API에서도 강제**됩니다. 현재는 파일 단위 정책이며, 함수 단위 허용 목록은 후속 구현 대상입니다.

## 3. Claude Code 연결 방식

```text
Windows Browser ── HTTP localhost ── Python GUI Server (WSL/Linux)
     │                                    │
     ├── 개발 환경 설정                     ├── 프로젝트별 로컬 프로필 저장
     ├── 작업 지시 + 대상 파일               ├── 선택 파일 UTF-8 내용 읽기
     └── Diff 검토 + 사용자 승인             └── claude -p (단발성 CLI 호출)
                                            │  ├── 작업 + 소스 + 빌드 문맥 (stdin)
                                            │  ├── JSON schema 제약
                                            │  ├── --tools "" / --strict-mcp-config
                                            │  ├── 임시 독립 작업 디렉터리
                                            │  └── 새 코드 제안만 반환
                                            ↓
                               검토 전에는 소스 쓰기 없음
                               승인 후 SHA-256 무결성 확인 + 파일 반영
```

CLI 실행에는 `-p`, JSON 구조화 출력, `--tools ""`, `--strict-mcp-config`, `--disable-slash-commands`, `--permission-mode plan`, `--no-session-persistence`, `--max-turns 1`을 사용합니다. 이 옵션은 모델이 Bash/Read/Edit 같은 도구나 MCP 서버를 사용해 **워크스페이스 파일을 직접 변경하지 못하도록 제한**하기 위한 것으로, 사용자-level Claude 설정이나 호스트 프로세스 전체를 별도 OS 샌드박스로 격리하는 것은 아닙니다. 서버는 대상 소스 디렉터리를 CLI 작업 디렉터리로 사용하지 않습니다.

Claude Code는 GUI 서버와 분리된 **외부 프로그램**입니다. CLI가 Claude에 보내는 데이터에는 **사용자의 지시문, 선택한 소스 파일 전체, 개발 환경 설정(빌드 명령·환경변수 포함)**이 포함됩니다. Claude Code의 인증 및 연결 설정에 따라 Anthropic 또는 구성된 AI 서비스로 전송될 수 있습니다. GUI 자체는 별도의 텔레메트리를 구현하지 않았지만 **전체 시스템이 오프라인이거나 외부 전송이 없다는 뜻은 아닙니다.** 사내 소스인 경우 승인된 계정·정책·네트워크/자료 전송 범위를 먼저 확인하세요. 비밀번호·토큰·API 키 등 비밀정보를 개발 설정에 입력하지 마세요.

## 4. 파일 구성

| 파일 | 역할 |
| --- | --- |
| `app.py` | 로컬 API, 프로젝트 설정 저장/검증, Claude Code CLI 호출, Diff, 승인·반려·복원 |
| `agents/code-dev.md` | 단일 Code-Dev 정책과 JSON 출력 계약 |
| `web/index.html`, `web/app.js`, `web/style.css` | Code-Dev + 개발 환경 설정 GUI |
| `demo_workspace/` | IFPMIC 충전 드라이버용 변경안 데모 (실제 보드 빌드 불가) |
| `tests/test_app.py` | 15개 테스트: 환경 설정·경로 정책·승인 흐름·가짜 CLI 연동·오류 처리 |

API: `GET /api/bootstrap`, `/api/claude/status`, `/api/history` · `POST /api/workspace`, `/api/config/save`, `/api/file`, `/api/propose`, `/api/proposal`, `/api/apply`, `/api/reject`, `/api/undo`.

설정 위치: `~/.config/ax-code-dev/profiles.json` (모드 0600, 소스 저장소 밖). 파일 수정 승인 시 원본 해시와 설정 revision이 유지되어야 반영합니다. 승인 내역과 제안은 메모리에만 보관되어 서버를 재시작하면 사라집니다.

## 5. 기능 범위와 한계

- **Code-Dev A단계만 지원:** 대상 파일 1개, UTF-8, 64KB 이하. 실제 빌드·테스트·플래싱·배포 기능 없음.
- **Demo 모드**는 지정 IFPMIC C 파일에 고정된 예시 변경안을 제시하며 외부 AI를 호출하지 않습니다.
- **Claude Code 모드**는 실제 설치·인증된 CLI가 필요합니다. 테스트는 **모의 CLI**로 진행했으며 실제 Anthropic 계정/모델의 요청 성공은 검증하지 않았습니다.
- 사용자 수준 Claude 설정이나 조직 정책을 서버가 자동 검증하지 않습니다. 후속 실무 적용 전 회사 보안 정책, 연결 승인, 데이터 보존 정책을 검토해야 합니다.
- Git Worktree 격리, 여러 파일 Patch 제안, 함수/범위별 정책, 영구 감사 로그 및 역할별 권한 통제는 아직 미구현입니다.

## 6. 테스트

```bash
python3 -m unittest discover -s tests -v
```

15개 자동 테스트: 변경안 생성/승인/반려/undo, CSRF와 경로 탈출 차단, 최초 프로필 저장과 영속화, 설정 버전 충돌, 빌드 명령 미실행, 변경 허용 범위, 모의 Claude Code CLI 호출(외부 네트워크 없음), CLI 미설치·오류·출력 파싱 실패 등.

## 다음 단계

Git Worktree 격리 및 Patch 단위 승인을 가장 먼저 고려합니다. 이어서 여러 관련 파일 문맥 전달, 스펙 연동, 승인 로그 영속화, 빌드·TC 에이전트와의 handoff 인터페이스를 추가할 수 있습니다.
