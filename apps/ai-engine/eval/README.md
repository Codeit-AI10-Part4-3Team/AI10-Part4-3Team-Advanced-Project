# apps/ai-engine/eval/

평가 자산(골든 데이터셋·지표) 공간입니다. `src/`와 라이프사이클이 달라 별도 디렉토리로 두되,
**채점 대상(검색·가드레일 출력)과 같은 배포 단위 안**에 둡니다 — 엔진이 바뀌면 채점 기준도
같은 PR에서 함께 움직여야 측정이 재현되기 때문입니다([ADR-0001](../../../docs/adr/0001-모노레포_채택.md)).

이 템플릿의 전제는 **"품질은 재현 가능한 자동 스크립트로 증명한다"** 입니다. 사람이 눈으로 확인한
결과가 아니라, 여기 있는 스크립트의 출력이 보고서·제출물의 근거가 됩니다.

## 구성

| 파일 | 역할 |
|---|---|
| `metrics.py` | 순수 지표 함수 — `(예측, 정답) → 점수`. I/O·모델 호출 없음 |
| `test_metrics.py` | 지표 함수 자체의 단위 테스트 (CI에서 실행됨) |
| `golden_dataset/*.jsonl` | 채점 기준 데이터. 변경 시 이유를 커밋 메시지에 남길 것 |
| `run_guardrail_detector.py` | 검출기 단위 시험 — 위반 예문을 `check_claims`에 직접 통과 (모델 호출 없음, 요금 0) |
| `run_metrics.py` | 지표 채점 — 수집된 회차 기록(JSONL)을 읽어 지표 표를 채웁니다 |

## 수집과 채점을 파일로 가릅니다

`run_metrics.py`는 **회차를 만들지 않고 읽기만 합니다.** 수집(스택을 띄워 지연을 재고, 채점
모델을 부르고, 임베딩을 뽑는 일)은 비싸고 비결정적이고 외부에 의존하는데, 채점은 순수하고
공짜여야 하기 때문입니다. 한 스크립트에 두면 지표 정의를 고칠 때마다 회차를 다시 사야 하고,
그러면 아무도 지표를 고치지 않게 됩니다.

```bash
python eval/run_metrics.py --describe          # 기록 스키마. 입력 불필요
python eval/run_metrics.py --input runs/x.jsonl
```

**2026-08-22 기준 수집은 아직 없습니다.** 무엇이 왜 비어 있는지는 `--describe`가 함께
출력합니다 — 특히 **브랜드 스타일 일치도는 막혀 있습니다**(브랜드 레퍼런스셋이 없습니다).

⚠️ **데이터가 없는 지표는 0이 아니라 "측정 안 함"으로 냅니다.** 0은 "쟀는데 0이었다"로 읽히고,
목표치와 나란히 놓이면 미달로 읽힙니다. 재지 않은 것과 재서 나쁜 것은 다릅니다.

## golden_dataset/ad_copy.jsonl — 스키마 (2026-08-22, 2026-08-24에 26건으로 확장)

**템플릿이 남긴 `example.jsonl`(질의응답 스키마: `question` / `expected_source_ids` /
`expected_behavior: answer|refuse`)을 지웠습니다.** 그 경로(`/v1/generate`, 템플릿 질의응답)는
2026-08-20에 이미 삭제됐고, 지금 파이프라인은 브리프를 받아 광고 카피·만화 대사를 생성하는
것이라 질문-답변 스키마가 애초에 대응하지 않았습니다.

각 줄은 이렇게 생겼습니다.

```json
{
  "id": "g-004",
  "caseType": "adversarial",
  "guardrailFocus": "number",
  "rationale": "왜 이 케이스가 있는지 - 사람이 읽는 설명",
  "request": {
    "outputType": "single_ad",
    "brief": { "productImageUrl": "...", "productName": "...", "sellingPoint": "...",
               "note": "...", "category": "...", "target": "...", "artStyle": "..." }
  }
}
```

`request`는 **`ai_engine.models.generation.DraftGenerateRequest`의 와이어 형태와 그대로
일치**하도록 만들었습니다 (`guardrailApplied`만 제외 - 아래 참고). **`draft:generate`를 실제로
호출해 카피를 만드는 수집 스크립트는 아직 없습니다** - 생기면
`DraftGenerateRequest.model_validate(case["request"])`로 바로 넣을 수 있어야 하고, 그 계약이
깨지면(필드 추가·이름 변경) 이 파일도 같은 PR에서 함께 고쳐야 합니다. 수집된 출력은
`run_metrics.py --input`이 읽는 JSONL로 쌓이고, 그 뒤 `claim_support_rate` 등으로 채점됩니다.

**`golden_dataset/guardrail_claims.jsonl`(검출기 단위 시험, `run_guardrail_detector.py`)과는
다른 파일이자 다른 지점을 잽니다.** `guardrail_claims.jsonl`은 사람이 미리 써 둔
`(copy, evidence)` 쌍으로 `check_claims` 함수 자체의 검출력만 재고 모델을 부르지 않습니다
(요금 0, 결정론적). `ad_copy.jsonl`은 브리프에서 실제로 카피를 생성하는 end-to-end
경로(생성 모델 포함, 요금 발생)를 겨냥하므로 둘은 서로 대체하지 않습니다.

**`guardrailApplied`는 케이스에 없습니다.** on/off 대조가 핵심 관측값이라 같은 케이스를
두 번(켜고/끄고) 돌리는 것은 수집 하네스의 몫이지 케이스 데이터가 아닙니다. 케이스 안에
박아 두면 대조군 쪽 실행이 애초에 불가능해집니다.

**`caseType`이 채점 방식을 가릅니다.**

| `caseType` | 뜻 | 채점 |
|---|---|---|
| `control` | 근거가 충분하거나(때로는 근거 문구를 그대로 재사용해야 하는) 안전한 브리프 | `guardrail.check_claims`가 자동 판정 |
| `adversarial` | 소구점이 모호해 모델이 근거 밖 수치·비교·최상급·수상 표현을 지어낼 위험이 큰 브리프 | `guardrail.check_claims`가 자동 판정 |
| `trap` | **효능·성분처럼 `check_claims`가 애초에 검출하지 못하는 갈래**를 겨냥한 브리프 | 자동 판정 불가 - 사람 또는 교차 채점 모델이 매 회차 출력을 보고 직접 판정 |

`trap` 케이스가 필요한 이유는 `guardrail.py` 자신의 문서화된 한계입니다: "효능과 성분은
검출하지 않습니다 ... 가드레일이 놓치는 것이지 허용하는 것이 아닙니다. 사람 리뷰와 eval
하네스가 그 구간을 봅니다." — 이 한계를 실제로 재려면 정규식이 못 보는 자리를 겨냥한 케이스가
있어야 측정이 가능합니다.

**`guardrailFocus`는 참고용 태그**입니다(`number` / `comparison` / `superlative` / `award` /
`efficacy_or_ingredient` / `none`). 실제 위반 갈래는 `check_claims`가 매 회차 출력에서
직접 판정하므로, 이 태그가 맞았는지 자체는 채점 대상이 아니고 보고서에서 케이스를 묶어
보는 용도입니다.

⚠️ **26개(2026-08-24 기준)는 07이 임의로 잡은 시작점**이지 확정된 표본 크기가 아닙니다.
품질 지표 목표치가 아직 가설인 것처럼(AGENTS.md), 골든셋이 몇 개면 충분한지도 실측 전에는
근거가 없습니다. 필요하면 늘리거나 카테고리를 더 쪼개세요 - 이 파일이 정본이니 바꾸면
이유를 커밋 메시지에 남기면 됩니다.

이 골든셋을 처음 놓으면서 comic을 16건(단일광고형 10건의 1.6배)으로 두텁게 잡았습니다.
comic은 칸 5개를 동시에 불러 실패 표면이 넓은데(N20-a, 한 칸만 막혀도 세트 전체 폐기),
표본이 적으면 그 위험을 못 잡기 때문입니다. `caseType`은 control 9 / adversarial 10 /
trap 7, `guardrailFocus`는 6종 태그 전부 최소 3건 이상입니다. `efficacy_or_ingredient`
(사람 판정 필요)가 7건으로 가장 많은데, `check_claims`가 애초에 못 잡는 갈래라 자동
판정으로는 안 늘어나는 위험이라 의도적으로 두텁게 뒀습니다.

## golden_dataset/brief_fill.jsonl — 스키마 (2026-08-24)

`ad_copy.jsonl`은 `draft:generate`(이미 채워진 브리프로 카피를 생성하는 단계)를 잽니다.
이 파일은 그 앞 단계인 **`brief:fill`(사진+텍스트로 category/target을 추론하는 단계)**을
잽니다. 재려는 것 자체가 다릅니다 - 저건 "생성된 말이 거짓말을 안 하는가"이고, 이건
"시스템이 애매한 입력 앞에서 억지로 결정을 안 내리는가"입니다.

각 줄은 이렇게 생겼습니다.

```json
{
  "id": "bf-006",
  "caseType": "ambiguous",
  "rationale": "왜 이 케이스가 있는지",
  "request": {
    "productName": "...", "sellingPoint": "...", "note": "...",
    "imagePlaceholder": "...", "imageDescription": "..."
  },
  "expected": {
    "needsInput": true, "field": "category", "reasonHint": "..."
  }
}
```

⚠️ **`request`는 `BriefFillRequest`와 필드 단위로 1:1 대응하지 않습니다.** `ad_copy.jsonl`의
`request`는 `DraftGenerateRequest.model_validate()`에 바로 넣을 수 있지만, `BriefFillRequest`는
`multipart/form-data`로 실제 이미지 바이트(`product_image`)를 요구합니다. 텍스트 파일인
JSONL은 그 바이트를 담을 수 없어 `imagePlaceholder`(자리표시 경로)와 `imageDescription`
(사람이 읽는 사진 설명, 채점 시 참고용)로 대신합니다. **이 두 키는 계약 필드가 아닙니다** -
수집 스크립트가 생기면 실제 이미지 파일을 별도로(커밋하지 않고, AGENTS.md의 개인정보·저작물
경고에 따라) 마련해 `imagePlaceholder` 경로에 채워 넣어야 각 케이스가 실행 가능해집니다.

⚠️ **텍스트만으로 애매한 축만 다룹니다.** 실제 서비스에서 category/target이 애매해지는
원인 중 상당수는 **사진 내용이 텍스트와 안 맞거나 텍스트를 보완하지 못하는 경우**일
텐데, 그건 실제 이미지 없이는 재현할 수 없습니다. 이 10건은 그 대신 "제품명·소구점 자체가
여러 카테고리에 걸치거나 아무 단서가 없는" 경우만 다루므로, 이미지 의존형 모호성은
**다루지 못한 채 남아 있습니다.** 실제 이미지가 갖춰지면 그 갈래를 추가하세요.

| `caseType` | 뜻 | `expected` |
|---|---|---|
| `sufficient` | 텍스트만으로 category/target이 분명함 | `needsInput: false` + 기대 category/target |
| `ambiguous` | 텍스트가 category 또는 target 중 하나를 좁히지 못함 | `needsInput: true` + `field`(어느 쪽이 막혔는지) + `reasonHint` |

**`sufficient`도 자동 채점 대상은 `needsInput: false` 여부뿐입니다.** 기대 category/target은
`ambiguous`의 `field`와 같은 참고용입니다 - bf-002의 기대 target `20대`에 엔진이
`20대 후반 직장인`을 돌려주는 것처럼 합당한 값이 여러 개 가능해서, 문자열 일치로 채점하면
그 판정 규칙을 채점하는 사람이 그때그때 지어내게 됩니다. category/target이 기대와 동떨어져
보이면 사람이 보고서에서 눈으로 확인하는 몫으로 남겨 둡니다.

`field`는 참고용입니다(bf-010 케이스 설명 참고) - `category`와 `target`이 동시에 막힌
케이스는 엔진이 둘 중 어느 쪽을 먼저 물어도 설계 위반이 아니므로, 채점에서 `field`
불일치 자체를 실패로 세지 마세요. **`needsInput` 여부(True/False)가 핵심이고, `field`는
보고서에서 케이스를 묶어 보는 용도**입니다 - `guardrailFocus`가 `ad_copy.jsonl`에서 하는
역할과 같습니다.

⚠️ **10개(2026-08-24)는 시작점입니다.** sufficient 5 / ambiguous 5이고, ambiguous는
`field: category` 4건 / `field: target` 1건으로 category 쪽에 치우쳐 있습니다 - target만
막히는 케이스(bf-009)가 상대적으로 적어, 필요하면 그쪽을 더 채우세요.

## ⚠️ 파일 이름이 CI 동작을 가릅니다

이 디렉토리는 pytest 수집 대상입니다(`pyproject.toml`의 `testpaths = ["tests", "eval"]`).
지표 함수가 보고 숫자의 근거인 만큼 회귀 검사가 필요하기 때문입니다. 따라서:

- `test_*.py` → **순수 지표 함수 단위 테스트 전용.** 외부 API를 부르면 안 됩니다.
- 실제 채점 실행(LLM 호출·골든셋 전량 채점)은 `run_*.py` 처럼 `test_`로 시작하지 않게 이름
  지으세요. CI가 수집하면 비용이 발생하고 결과가 비결정적이 됩니다.

## 측정 규칙

- **지표 함수는 순수 함수로.** 구현이 바뀌어도 같은 점수 계산을 재사용할 수 있어야 합니다.
- **채점 모델 ≠ 생성 모델.** 자기채점 편향을 피하기 위한 규약이며, 방법론 신뢰도로 직결됩니다.
- **카피 사실 일치율에 어휘 겹침(`source_fidelity`)을 쓰지 마세요.** 광고는 근거가 한 문장이고
  카피가 짧아 질의응답의 전제가 성립하지 않습니다. 실측에서 **거짓 음성**이 났습니다 —
  `타사보다 2배 두꺼운 원단, 무향 무알코올`이 0.56으로 통과합니다(위반 문구를 근거 어휘로
  감싸면 점수가 오릅니다). 근거는 [ADR-0019](../../../docs/adr/0019-광고_카피_가드레일은_금지_표현을_검출한다.md).
  지표 함수는 `claim_support_rate`이고, **주장 단위 채점은 모델이 합니다.**
- **더미 데이터로 측정하지 마세요.** 골든셋의 `productName` / `sellingPoint` / `note`는
  현실적인 제품 정보여야 실측치가 의미를 가집니다. (예전 이 자리에 있던 `fixtures/` 참조는
  2026-08-20 템플릿 질의응답 경로 삭제와 함께 그 디렉토리 자체가 없어져 지웠습니다.)
- **가드레일 보고 숫자는 델타가 아니라 절대값입니다** (2026-08-21 회의,
  [회의록](../../../docs/회의록/2026-08-21_미결정_5건_확정.md) 03번 안건). "몇 건 중 몇 건이
  위반이었다"를 **표본 수와 함께** 적습니다. 규칙의 정본은
  [생성_파이프라인.md](../../../docs/기술문서/생성_파이프라인.md) 5.3절입니다.
  - 원래 지표는 `suppression_rate(off, on)` 이었는데, 2026-08-20 실측에서 **가드레일을 끈
    대조군의 위반이 0건**이라 차이가 생길 자리가 없었습니다. 델타가 0인 것은 가드레일이
    무력해서가 아니라 측정이 설계되지 않아서입니다.
  - **`suppression_rate` 함수는 지우지 않았습니다.** 위반 사례가 관측되면 다시 쓸 수 있는
    순수 함수이고, 지금 상태는 "폐기"가 아니라 **"분모가 없어 보고에 쓰지 않음"** 입니다.
    새로 쓰는 채점 스크립트가 이 함수를 보고 숫자로 삼지 않으면 됩니다.
- **대조군을 "테스트를 통과시키려고" 끄지 마세요.** 보고 지표가 절대값으로 바뀐 것과 별개로,
  켜 둔 채 "가드레일 끔"이라고 기록하면 대조군 관측 자체가 거짓이 됩니다.
- **end-to-end 지연은 backend까지 걸친 지표**입니다. 여기서 채점하되 backend를 파이썬 import
  하지 말고, 기동된 서비스에 HTTP로 측정하세요(앱 간 import 금지 규칙).
- 골든셋 `*.csv` / `*.jsonl`은 루트 `.gitignore`의 `!apps/ai-engine/eval/**/*` 예외로 커밋
  가능합니다. 디렉토리를 옮기면 그 예외 줄도 함께 옮기세요.
