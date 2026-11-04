# AX Code-Dev Studio

**Claude Code CLI 기반 코드 변경 GUI**입니다. 개발 환경을 설정하고 변경안을 생성한 뒤, Diff를 검토하여 승인한 파일만 수정합니다.

## 빠른 시작

**필요:** Python 3.9+, Claude Code CLI(설치 및 로그인 완료), 웹 브라우저

```bash
git clone https://github.com/Dong-Ha/CODEdev.git
cd CODEdev
claude auth status
python3 app.py
```

Windows 브라우저에서 **http://127.0.0.1:8765** 접속

> GUI 서버와 Claude Code는 **같은 WSL/Linux 환경**에서 실행해야 합니다.

## 사용 순서

1. **개발 환경:** 프로젝트 경로를 연결하고 빌드 명령어, 수정 허용·제외 경로, 코딩 규칙을 설정해 저장합니다.
2. **Code-Dev:** 수정할 소스 파일과 요구사항을 선택해 Claude Code에 변경안을 요청합니다.
3. **Diff 검토:** 기존 코드와 제안 코드를 비교합니다.
4. **승인 또는 반려:** 승인할 때만 파일을 수정하며, 적용한 변경은 되돌릴 수 있습니다.

개발 환경 설정은 이후에도 수정할 수 있으며 `~/.config/ax-code-dev/profiles.json`에 저장됩니다.

## 현재 지원 범위

- 한 번에 **소스 파일 1개** 변경 제안 (UTF-8, 최대 64KB)
- 파일 수정 범위 제한, 승인 전 무수정, 변경 이력 및 되돌리기
- **빌드 명령어는 설정 정보로만 사용**하며 빌드·테스트·플래싱은 실행하지 않음
- `sample_workspace/`: IFPMIC 샘플 코드 (실제 보드 빌드용 아님)

## 주의사항

Claude Code 호출 시 작업 요청, 선택한 소스, 개발 설정이 외부 AI 서비스로 전송될 수 있습니다. **사내 코드 적용 전 보안 정책을 확인**하고, 설정에 비밀번호·토큰 등 비밀정보를 입력하지 마세요.

실제 Claude Code 계정 연동은 별도 확인이 필요합니다. 자동 테스트는 모의 CLI를 사용합니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```
