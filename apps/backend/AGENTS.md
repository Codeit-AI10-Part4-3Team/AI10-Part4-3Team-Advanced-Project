# apps/backend — 디렉토리 규칙

루트 [/AGENTS.md](../../AGENTS.md)가 전역 정본입니다. 아래는 이 디렉토리에서만 유효한 규칙입니다.

- **`backend_core`는 `api`를 절대 import하지 않습니다.** 도메인 로직은 FastAPI 없이 실행·테스트
  가능해야 평가 하네스와 오프라인 도구가 그 로직을 직접 부를 수 있습니다.
- **라우터는 얇게**: 요청 검증 → 도메인 호출 → 응답 매핑. 라우터 안의 비즈니스 로직은 결함입니다.
- **`apps/ai-engine`을 절대 import하지 않습니다(역도 동일).** 결합은 `packages/contracts`의
  HTTP 계약뿐입니다.
- **ai-engine이 죽어도 세션 생성은 201 + `messageMode: degraded`로 진행됩니다.** 열화는 설계된
  동작이지 버그가 아니므로, 이것을 "고치는" 변경은 설계 위반입니다.
  ⚠️ **열화가 허용된 자리는 `brief:fill` 하나뿐입니다** ([ADR-0005](../../docs/adr/0005-열화_폴백은_자동화_생략으로_한정.md)).
  시안 생성과 부분 교체와 렌더는 폴백 없이 실패합니다 — 사전 승인 문안을 되살리는 변경은
  입력에 없는 주장을 내보내는 경로입니다. 템플릿의 `official_fallback`과 `FALLBACK_TEXT`는
  2026-08-19에 삭제되었습니다.

## 실행

```bash
cd apps/backend && pytest -q     # 반드시 이 디렉토리를 cwd로 — 루트 실행은 수집 단계에서 깨집니다
cd apps/backend && mypy
```
