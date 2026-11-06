# 출처와 변경 고지

이 패키지는 Anthropic feature-dev 프로젝트에서 가져와 수정한 파일을 포함합니다.
https://github.com/anthropics/claude-plugins-official/tree/fb370c077e8904ce5a0fbe5c89084f5171863c1f/plugins/feature-dev

원본 파일은 agents/code-explorer.md, agents/code-architect.md, agents/code-reviewer.md입니다.
원본 Apache License 2.0을 LICENSE에 그대로 포함했습니다. 패키지를 재배포할 때 이 고지와 LICENSE를 함께 보존하세요.

2026-11-06 CODEdev용 변경 사항:

- 이름 충돌을 피하도록 전문 에이전트 3개의 이름에 ax- 접두사를 붙였습니다.
- 기존 도구 목록을 로컬 읽기 전용 분석용 Read, Grep, Glob으로 바꿨습니다.
- 원본 전문 에이전트의 분석·설계·리뷰 기준과 Sonnet 선택을 유지하고 번역 전 CODEdev 커밋 c595f9546b15633e0e065ddfbf2bd50b1d631396의 영어 지침을 기준으로 본문 전체를 한국어로 번역했습니다.
- CODEdev 범위 제한, 명시적인 리뷰 범위와 위키 근거 연결 규칙을 추가했습니다.
- 원본 commands/feature-dev.md의 흐름을 ax-code-dev 메인 에이전트로 재구성하고 요구사항 파악과 코드 탐색 사이에 독립 위키 단계를 추가했습니다.
- CODEdev의 agents/code-dev-wiki/wiki-explorer.md를 등록 가능한 전문 에이전트로 조정했습니다.
- 독립 설치, 재현 가능한 ZIP 생성과 사용 문서를 추가했습니다.
- 에이전트 설명·단계 제목·출처 고지를 한국어로 바꾸고 실행 식별자, 도구 이름, 모델 이름, 데이터 키와 상태 값은 유지했습니다.

번역 기준: 원문의 문장·항목 순서, 조건, 수치와 지시 강도를 최대한 충실하게 유지했습니다. 특히 리뷰 확신도 50·75·100점 설명과 지적이 없을 때의 기준 충족 확인 문구를 원문대로 옮겼습니다. 원본 지침과 이미 추가된 AX 조정 사항은 각각의 절로 구분하여 보존합니다.

이 패키지는 CODEdev용으로 조정한 배포본이며 Anthropic 공식 배포본이 아닙니다.
