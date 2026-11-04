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
| **직접 요청** | 개발 환경 저장 → SRS, SDD, Jira 본문 또는 자유 요청 입력 → 변경안 생성 (대상 파일 선택은 선택 사항) |
| **에이전트 수신** | SDD 인계 또는 검증 피드백을 API로 접수 → 수신함에서 작업 확인 → 변경안 생성 또는 열기 |

두 경로 모두 **Diff 검토 → 승인·반려 → 결과 확인**을 거칩니다. 승인 전에는 소스를 수정하지 않습니다.

에이전트 연동 방법과 예시는 [docs/orchestration.md](docs/orchestration.md)를 참고하세요.

## 개발 환경

프로젝트별로 **빌드 명령어, ARCH, CROSS_COMPILE, 수정 허용·제외 경로, 코딩 규칙**을 설정하고 나중에 수정할 수 있습니다. **Target File을 비워두면** 허용 파일 목록에서 자동 선택하며, 불확실하면 직접 선택하도록 안내합니다. 빌드 명령어는 참고 정보이며 실행하지 않습니다. 설정은 `~/.config/ax-code-dev/profiles.json`에 저장됩니다.

**현재 범위:** 한 번에 UTF-8 파일 1개(최대 64KB), 실제 빌드·테스트·플래싱 없음. 수신함과 작업 이력은 서버를 재시작하면 초기화됩니다.

**보안:** Claude Code 호출 시 작업 요청, 소스 및 개발 설정이 AI 서비스로 전송될 수 있습니다. 사내 소스는 조직 정책을 확인하고, 설정에 비밀정보를 입력하지 마세요.


## Claude Code 대화 및 실행 기록

요청 전송 후 GUI에서 **실행 상태, 요청 원문, 응답 요약, 실패 사유**를 확인할 수 있습니다. 기록은 서버 메모리에만 보관되며 재시작 시 사라집니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```
