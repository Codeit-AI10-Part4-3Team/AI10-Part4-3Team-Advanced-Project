# apps/ai-engine — 디렉토리 규칙

루트 [/AGENTS.md](../../AGENTS.md)가 전역 정본입니다. 아래는 이 디렉토리에서만 유효한 규칙입니다.

- **독립 배포 단위입니다.** `apps/backend`를 절대 import하지 않습니다(역도 동일). 허용된 결합은
  `packages/contracts`의 HTTP 계약뿐 — 이 선을 넘는 import 한 줄이 "독립 배포 가능한 AI 모듈"이라는
  성질을 조용히 없앱니다.
- **내부 파이프라인은 단방향**: 입력 정규화 → 프롬프트 조립 → 생성 → 가드레일 검증 → 출력.
  역방향 의존 금지. 다이어그램: [아키텍처.md](../../docs/공통_가이드/아키텍처.md).
- **가드레일을 목으로 대체해 테스트를 통과시키지 마세요.** on/off 델타가 보고 지표라, 우회한
  가드레일은 테스트를 고치는 게 아니라 측정을 무효로 만듭니다.

## eval/ — 파일 이름이 CI 동작을 가릅니다

- `pyproject.toml`이 `testpaths = ["tests", "eval"]`이라 **`eval/`도 pytest 수집 대상**입니다.
- `eval/` 안의 `test_*.py`는 **순수 지표 함수의 단위 테스트에만** 쓰세요. 실제 채점 하네스 실행
  스크립트는 `run_*.py` — 이름을 틀리면 CI가 외부 API를 호출합니다(비용·비결정성).
  정본: [eval/README.md](eval/README.md).
- **지표 함수는 순수 함수** `(예측, 정답) → 점수`. I/O·모델 호출 금지. **채점 모델 ≠ 생성 모델**
  (자기채점 편향 배제).

## 실행

```bash
cd apps/ai-engine && pytest -q                      # 앱 전체 (반드시 이 디렉토리를 cwd로)
cd apps/ai-engine && pytest tests/test_x.py -q      # 파일 하나 / ::test_name / -k 매칭
cd apps/ai-engine && mypy                           # 타입 검사 (cwd여야 설정을 집습니다)
```

- 무거운 의존(LangChain·벡터 DB 등)은 이 앱의 optional extra로 — core에 넣으면 CI가 매번
  전체 스택을 끌고 옵니다(CI는 core+`dev`만 설치).
