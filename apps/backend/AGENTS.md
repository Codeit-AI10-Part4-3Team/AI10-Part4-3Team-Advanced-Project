# apps/backend — 디렉토리 규칙

루트 [/AGENTS.md](../../AGENTS.md)가 전역 정본입니다. 아래는 이 디렉토리에서만 유효한 규칙입니다.

- **`backend_core`는 `api`를 절대 import하지 않습니다.** 도메인 로직은 FastAPI 없이 실행·테스트
  가능해야 평가 하네스와 오프라인 도구가 그 로직을 직접 부를 수 있습니다.
- **라우터는 얇게**: 요청 검증 → 도메인 호출 → 응답 매핑. 라우터 안의 비즈니스 로직은 결함입니다.
- **`apps/ai-engine`을 절대 import하지 않습니다(역도 동일).** 결합은 `packages/contracts`의
  HTTP 계약뿐입니다.
- **ai-engine이 죽어도 200 + `messageMode: official_fallback`이 정상입니다.** 열화 폴백은 설계된
  동작이지 버그가 아니므로, 이것을 "고치는" 변경은 설계 위반입니다.

## 실행

```bash
cd apps/backend && pytest -q     # 반드시 이 디렉토리를 cwd로 — 루트 실행은 수집 단계에서 깨집니다
cd apps/backend && mypy
```
