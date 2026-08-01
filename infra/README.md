# infra/

로컬·배포 공용 인프라 정의입니다. 스택 기동, 환경변수 템플릿, 프로비저닝 문서가 여기 모입니다.

```bash
cp infra/.env.example infra/.env        # 값 채우기 — ⚠️ .env는 커밋 금지
docker compose -f infra/docker-compose.yml up --build
```

## 파일

| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | 전체 스택(backend + ai-engine). 로컬과 배포가 같은 파일을 씁니다 |
| `.env.example` | **키 이름만** 담은 템플릿. 값은 절대 넣지 마세요 |
| `.env` | 실제 값 — `.gitignore` 대상. 존재해도 커밋되지 않습니다 |

## 시크릿 취급 (공개 저장소 전제)

커밋된 키는 푸시되는 순간 공개된 것으로 간주하세요. 되돌리는 방법은 revert가 아니라
**폐기 후 재발급**입니다. 방어선은 세 겹이고, 세 겹 다 필요합니다:

1. GitHub Push protection — **제휴 발급사 패턴만** 잡습니다.
2. pre-commit `detect-private-key` — **PEM 개인키만** 잡습니다.
3. **gitleaks** — 위 둘의 사각지대(일반 API 키 문자열)를 덮습니다. pre-commit 훅(staged) +
   CI의 전체 트리 스캔이 **한 쌍**입니다. 훅 entry가 `--staged` 고정이라
   `pre-commit run --all-files`로는 아무것도 검사하지 않으므로, CI 스텝을 지우면 훅을
   설치하지 않은 사람의 키를 아무도 막지 못합니다.

## 새 환경변수를 추가할 때

1. `.env.example`에 **키 이름과 설명**을 추가 (값은 빈칸)
2. `docker-compose.yml`의 해당 서비스 `environment:`에 전달 (`${VAR:-기본값}`)
3. 앱의 설정 클래스(`backend_core/config.py` 등)에 필드 추가 — 접두어 규약을 지킬 것
4. 필요하면 CI/배포 시크릿에도 등록

빠뜨리기 쉬운 것은 4번입니다. 로컬에서만 되는 변수는 배포에서 조용히 기본값으로 동작합니다.

## 배포

> TODO: 배포 대상(클라우드·리전·인스턴스 크기)과 프로비저닝 절차를 여기에 적으세요.
> 결정의 배경은 `docs/adr/`에 ADR로 남기고, 이 문서에는 **재현 절차**를 남깁니다.
