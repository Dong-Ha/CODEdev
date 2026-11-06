# CODEdev 독립형 에이전트 패키지

플러그인 없이 사용하는 **메인 에이전트 1개 + 전문 에이전트 4개**입니다.
Claude Code CLI와 인증, Python 3.10 이상이 필요합니다. Python은 설치·ZIP 생성에만 사용하며 추가 패키지는 필요 없습니다.

## 구성과 순서

| 단계 | 작업 | 실행 주체 |
| --- | --- | --- |
| 1 | 요구사항 파악 | ax-code-dev |
| 2 | 독립 Wiki 탐색 | ax-wiki-explorer 1개, 결과를 메인이 확인 |
| 3 | Wiki와 코드 대조 | ax-code-explorer 2~3개 |
| 4 | 미결 사항 해소 | ax-code-dev |
| 5 | 대안 비교·선택 | ax-code-architect 2~3개, 선택은 메인 |
| 6 | 구현·실행 검증 | ax-code-dev |
| 7 | 검토·수정 확인 | ax-code-reviewer 3개, 수정은 메인 |
| 8 | 결과와 인계 | ax-code-dev |

원본 1단계와 2단계 사이에 Wiki 탐색을 삽입하고 후속 단계를 재번호화했습니다.
Wiki 결과가 준비되기 전에 코드 탐색을 시작하지 않습니다. 같은 단계의 독립적인 전문 에이전트 호출은 병렬 실행합니다.

에이전트 정의는 `.claude/agents/`에 있습니다. 설치 파일은 다른 프로젝트의 설정을 덮어쓰지 않습니다.

## 설치와 실행

ZIP을 풀면 `code-dev-standalone/` 폴더가 나옵니다. WSL에서는 해당 폴더에서:

```bash
python3 install.py --project /home/user/repos/linux --check
python3 install.py --project /home/user/repos/linux
cd /home/user/repos/linux
claude --agent ax-code-dev
```

Windows에서는 다음과 같이 실행할 수 있습니다. 실제 개발 대상이 WSL 파일 시스템이면 WSL에서 설치·실행하세요.

```powershell
py -3 install.py --project "C:\work\my-project" --check
py -3 install.py --project "C:\work\my-project"
Set-Location "C:\work\my-project"
claude --agent ax-code-dev
```

대상 프로젝트의 `.claude/agents/`에 에이전트 5개와 LICENSE/NOTICE를 설치합니다.
이미 같은 파일이면 그대로 두고, 다른 내용이 있으면 어떤 파일도 덮어쓰지 않고 종료합니다. 업데이트 시 충돌 파일을 백업·제거한 다음 재설치하세요. `--check`는 파일이나 폴더를 만들지 않습니다.

메인과 전문 에이전트는 동일한 세션에서 등록된 `ax-*` 이름을 사용합니다. 메인은 현재 세션의 모델을 상속하고, Wiki도 호출자의 모델을 상속합니다. 원본 전문 에이전트 3개는 `sonnet`을 유지합니다. `.claude/agents/` 전체가 함께 설치되어야 합니다.

플러그인 설치, `/feature-dev` 호출, `--plugin-dir`, 외부 에이전트 다운로드는 필요 없습니다. Claude Code 자체와 모델 서비스는 별도로 필요합니다. 실제 CLI에서 `Agent(...)` 허용 목록과 `--agent`가 지원되어야 하며 지원하지 않는 버전에서는 CLI를 갱신하세요.

## CODEdev 요청 사용

CODEdev에서 조회한 상세 JSON의 `task.payload`, `{ "payload": ... }`, payload 자체를 지원합니다. 대상 프로젝트의 읽기 허용 위치에 요청 JSON을 저장한 다음 메인 세션에 다음처럼 전달합니다.

```text
/home/user/repos/linux/code-dev-request.json을 읽고 작업을 시작해.
입력은 CODEdev의 task.payload 형식이야.
먼저 요구사항, Wiki, 코드를 분석하고 설계안을 제시해.
이번에는 분석과 제안까지만 진행해.
```

이후 설계와 적용 범위, 실행 가능한 검증을 결정하면 같은 세션에서 구현을 진행합니다. 이미 동일한 범위에 대한 승인이 있으면 중복 승인을 요구하지 않습니다.

- `environment.wiki_link`는 **로컬 파일 또는 폴더 경로**입니다. URL 조회로 바꾸지 않습니다.
- Wiki가 없으면 2단계는 `skipped/not_configured`로 기록하고 빈 wiki_context를 전달합니다.
- 지정 경로의 오류·읽기 거절·지원하지 않는 형식은 `missing/denied/unsupported`로 구분합니다. 필수 근거가 없으면 중단하며, 코드로 확인 가능하면 한계를 기록하고 진행합니다.
- 외부 Wiki는 승인된 별도 읽기 범위가 필요합니다. 위키는 수정하지 않습니다.
- W1, W2 등의 문서 근거 ID를 코드 대조, 설계, 구현, 리뷰와 최종 결과까지 유지합니다.
- 소스는 `scope.read_boundary` 안에서 읽고, 현재 재검증된 `scope.editable_files`와 허용/제외 규칙에 맞춰 수정합니다. 현재 환경 revision을 확인할 수 없으면 실제 적용을 보류합니다.
- 비대화형 `-p` 실행은 질문·승인을 자동 처리하지 않습니다. 호출자가 needs_input 결과를 읽어 답변과 실행 상태를 다시 전달해야 합니다.

**CODEdev 웹의 “바로 전달”은 기존 텍스트 전송 모드입니다. 이 패키지를 등록했다고 웹 실행기가 자동으로 개발 모드로 바뀌지 않습니다.** 이 배포의 실행 경로는 위 수동 CLI 명령입니다. HTTP 실행 인수/결과 저장·취소·권한 강제는 별도 연결 작업입니다.

## ZIP 재생성

폴더에서 실행:

```bash
python3 build_zip.py /tmp/code-dev-standalone.zip
```

CODEdev 저장소 루트에서 배포본 갱신:

```bash
python3 agents/code-dev-standalone/build_zip.py downloads/code-dev-standalone.zip
```

ZIP은 이 폴더의 선언된 10개 파일만 포함합니다. 경로·타임스탬프·권한을 고정해 동일한 입력에서 재현 가능하며 `.claude` 숨김 폴더도 포함합니다.

## 출처와 검증 범위

Anthropic feature-dev 고정 커밋의 전문 에이전트 지침의 문장·항목·조건과 지시 강도를 최대한 충실하게 한국어로 옮기고 도구·이름·AX 전달 계약을 조정했습니다. 에이전트 식별자와 도구·모델·데이터 키는 실행 호환성을 위해 유지하며, LICENSE는 원문을 보존합니다. 자세한 변경과 원본 링크는 [NOTICE.md](NOTICE.md), 라이선스는 [LICENSE](LICENSE)를 참조하세요.

설치 충돌·심볼릭 링크·경로 공백·재설치·ZIP 내용과 재현성을 자동 검사합니다. 정적 구조/설치 검사는 실제 모델 위임·품질·토큰 사용 검증을 대신하지 않습니다.

번역 대조 기준은 [한국어 번역 전 CODEdev 버전](https://github.com/Dong-Ha/CODEdev/tree/c595f9546b15633e0e065ddfbf2bd50b1d631396/agents/code-dev-standalone/.claude/agents)입니다. 원문 본문과 AX 조정 사항을 각각 보존했으며, 번역을 이유로 새로운 실행 정책을 추가하지 않았습니다.
