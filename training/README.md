# training — 브랜드 스타일 파인튜닝 파이프라인

이미지 생성 모델을 **브랜드 스타일에 맞게 학습**시키는 오프라인 파이프라인입니다.
서빙(`apps/ai-engine/`)과는 **학습 산출물(어댑터 가중치 + 메타데이터)로만** 연결됩니다.

## 이 폴더가 비어 있는 이유 (2026-08-20)

**로컬 모델을 채택하지 않기로 확정했습니다.** 미결정_대장 A-5(로컬 모델 채택 여부)가
검증 4순위 결과로 닫혔고, `data/` `runs/` `src/training/`이 비어 있는 것은 잊어버린
것이 아니라 그 결정의 결과입니다.

근거는 두 갈래입니다.

- **한글 카피 렌더링에서 로컬 후보 셋이 전부 실패했습니다.** FLUX.1-schnell, Qwen-Image
  Q4, SDXL 중 어느 것도 한글 카피를 모델이 직접 정확히 그리지 못했습니다(글자 없음 0/10,
  철자 정확도 0/5, 1088 x 1088 단일 광고형 조건). 각각의 조건에서, gpt-image-2는
  3456 x 2304 만화형 조건으로 120칸 오탈자 0건입니다 - 두 수치는 서로 다른 실험이라
  직접 비교 대상은 아닙니다
  ([로컬모델_탐색_보고서.md](../docs/보고서/로컬모델_탐색_보고서.md),
  [생성_경로_비교표.md](../docs/보고서/생성_경로_비교표.md)).
- **GCP `g2-standard-4`(L4 24GB, 호스트 RAM 16GB) 기준 셀프호스팅 타당성 검토**에서
  픽셀 동등 재현이 불가능하고, 호스트 RAM 16GB가 실질 병목이라 20B급 모델은 배제되며,
  FLUX.1-dev, FLUX.2-dev 등 강한 후보는 비상업 라이선스라 이 상업 서비스에 쓸 수 없다는
  결론이 나왔습니다.
- **비용은 단일 광고형에서만 근거로 썼습니다.** 만화형에서는 gpt-image-2가 오히려
  자체 호스팅 추정치보다 비싸 방향이 반대이므로, 만화형에 대한 판단은 비용이 아니라
  한글 렌더링과 라이선스, RAM 병목이 이유입니다.

판정자 임동규, 송기하 두 사람 모두 동의해 검증 4순위(B-15)를 통과했습니다. 확정 근거:
[2026-08-20 회의록](../docs/회의록/2026-08-20_검증4순위_로컬모델_미채택.md).

**채택하지 않는다고 GPU를 안 쓰는 것은 아닙니다.** L4는 그대로 남아 있고, 이미지 생성은
API(gpt-image-2)로 유지합니다 - 로컬 모델이 오히려 앞섰던 화풍(브랜드 톤) 통제는
IP-Adapter 실험에서 이미 확인됐으므로, 그 자산을 다른 방식으로 쓸지는 별도 판단입니다.

## 왜 `apps/` 가 아니라 최상위인가

`apps/` 아래의 것들은 **상시 기동되는 배포 단위**(자체 Dockerfile + `/health` + CI 매트릭스 항목)라는
규약을 갖습니다. 학습은 그 규약에 맞지 않습니다 — 요청을 받지 않고, 사람이 트리거하며, 몇 시간
돌다 끝나고, GPU 점유 프로파일이 추론과 정반대입니다. `apps/trainer/`로 두면 CI 매트릭스가
"떠 있지 않은 서비스"의 헬스체크를 기다리게 되고, 그 불일치를 맞추느라 규약 쪽이 무너집니다.

배경과 대안 검토: [ADR-0002](../docs/adr/0002-학습_파이프라인_배치.md).

## 서빙과의 이음매 (여기가 유일한 연결점)

```mermaid
flowchart LR
    subgraph TR["training/ - 오프라인"]
        DATA[("data/ 데이터셋 폴더<br/>이미지 + 캡션<br/>커밋 금지")]
        CFG["configs/ 학습 설정 yaml<br/>커밋 대상<br/>재현의 단일 원천"]
        PREP["prepare<br/>정규화 · 개인정보 제거"]
        TRAIN["train<br/>LoRA"]
        EXPORT["export<br/>adapter_card.json 생성"]
        RUNS[("runs/ 실행별 폴더<br/>가중치 + 카드<br/>커밋 금지")]
    end
    AE["apps/ai-engine<br/>추론 서빙"]

    DATA --> PREP
    CFG --> PREP
    CFG --> TRAIN
    PREP --> TRAIN --> EXPORT --> RUNS
    RUNS ==>|"파일 전달<br/>양방향 import 금지"| AE

    classDef gitignored fill:#eef2f7,stroke:#5a6b7d,stroke-dasharray:4 3
    class DATA,RUNS gitignored
```

- 학습 코드는 `apps/` 아래 어떤 패키지도 **import하지 않습니다**(역도 동일). 두 방향 모두
  경계 위반이며, 한 줄이라도 넘어가는 순간 "학습 없이도 서빙이 뜬다"는 성질이 사라집니다.
- 넘기는 것은 **파일**입니다: 어댑터 가중치 + 그 가중치를 설명하는 `adapter_card.json`
  (base 모델 ID, 학습 config 해시, 데이터셋 버전, 학습 일시). 카드 없는 가중치는
  **재현 불가능한 산출물**이므로 서빙에 올리지 마세요.
- 가중치 자체는 커밋하지 않습니다(`.gitignore`의 `*.safetensors` 등). 배포는 오브젝트
  스토리지 또는 VM 로컬 경로를 거칩니다 — 경로 규약은 `infra/` 소관입니다.

## 레이아웃

```
training/
  configs/        학습 하이퍼파라미터 (YAML, 커밋 대상 — 재현의 단일 원천)
  data/           브랜드 이미지·캡션 데이터셋 (커밋 금지, README만 추적)
  runs/           학습 산출물·로그 (커밋 금지, 재생성 가능)
  src/training/   학습 코드 (P1에서 추가 — 아래 "코드를 추가할 때" 참고)
```

## 실행 (P1 이후)

```bash
python -m training.prepare --config training/configs/<name>.yaml   # 데이터셋 정규화
python -m training.train   --config training/configs/<name>.yaml   # 학습
python -m training.export  --run training/runs/<run-id>            # 어댑터 카드 생성
```

> 아직 `src/training/`은 비어 있습니다. **config가 먼저, 코드가 다음**입니다 —
> 하이퍼파라미터가 코드에 하드코딩되면 그 실험은 재현되지 않습니다.

## 코드를 추가할 때 (린트 계약)

`training/`은 CI 매트릭스(mypy·pytest)에 **들어 있지 않지만** ruff는 적용됩니다 —
`.pre-commit-config.yaml`의 ruff `files` 정규식에 `training`이 포함되어 있고, CI의
required 잡인 `Pre-commit hooks`가 `--all-files`로 그것을 돌립니다.
루트 `pyproject.toml`의 ruff `src`에도 `training/src`가 이미 등록되어 있어, 첫 코드가
들어오는 순간부터 isort가 `training`을 1st-party로 인식합니다.

**mypy·pytest까지 필요해지면** 그때는 앱 승격 논의 대상입니다. required check를 늘리는
변경이므로 `ci.yml` matrix, `scripts/setup-github.sh`의 `contexts`, 루트 `pyproject.toml`,
`CODEOWNERS` **네 곳을 같은 PR에서** 고쳐야 합니다.

## 데이터 취급

- 브랜드 이미지의 **권리 확인이 끝난 것만** `data/`에 둡니다. 출처와 이용 범위는
  `data/README.md`의 표에 기록하세요 — 기록되지 않은 데이터로 학습한 모델은
  배포 판단을 내릴 수 없습니다.
- 데이터셋에 버전을 붙이고(`brand-v1`, `brand-v2`) config에 그 이름을 적으세요.
  "그때 그 데이터"가 무엇이었는지 모르면 지표 비교가 의미를 잃습니다.
