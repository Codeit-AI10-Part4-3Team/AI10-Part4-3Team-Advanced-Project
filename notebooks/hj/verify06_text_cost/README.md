# 검증 6순위 나머지 절반 - 텍스트 단가와 가드레일 델타 예문

`brief:fill` + `draft:generate` + `draft:patch` 의 회차당 토큰과 USD 를 재고, 같은 회차에서
대조군의 위반율을 함께 봅니다. 호출 1회가 곧 요금이라 두 목적을 나누어 돌리면 같은 돈을 두 번
씁니다.

결과: [RESULTS.md](RESULTS.md). 조건: [conditions.py](conditions.py).

## 왜 이제야 잴 수 있는가

검증 6순위는 2026-08-14 에 이미지 단가만 재고 멈췄습니다. 텍스트 세 이음매는 카피 생성 경로가
TBD 라 잴 대상이 없었기 때문입니다. 08-19 에 경로가 확정되고(기획서 13.2 유지) 08-20 에 실물
분기가 배선되면서 대상이 생겼습니다.

토큰 수는 `ai_engine.usage` 가 로그로 남기는 것을 그대로 주워 담습니다. **엔진에서 값을
반환받는 특별한 통로를 만들지 않은 이유는, 배포 뒤에 같은 방법으로 집계해야 하기 때문입니다.**

## 예문이 이 실험의 핵심입니다

2026-08-20 회차에서 무난한 소구점으로는 대조군에서도 위반이 검출되지 않았고, 모델이 소구점을
되풀이하는 형태만 관찰됐습니다. 그 상태로 on/off 대조를 돌리면 양쪽 모두 0 이 나와 **델타가
0** 이 됩니다. 가드레일이 효과가 없어서가 아니라 위반이 일어날 여지가 없는 입력을 줬기
때문입니다.

그래서 `conditions.py` 의 예문 4종은 위반이 필연적으로 나오도록 설계했습니다. **그럼에도
2026-08-20 회차에서 네 갈래 모두 유도에 실패했습니다** - 무엇이 어떻게 실패했는지는
RESULTS.md 2.4절입니다.

## 실행

```bash
pip install -r requirements.txt
export ADGEN_MODEL_API_KEY=...              # infra/.env 에 두고 export. 커밋 금지
export ADGEN_PRICE_INPUT_PER_MTOK=1.25      # 없으면 토큰만 남고 USD 열은 비웁니다
export ADGEN_PRICE_OUTPUT_PER_MTOK=10.00

python run_cost.py --dry-run                                   # 계획만, 호출 없음
python run_cost.py --rounds 1 --guardrail off --yes            # 예문 6회
python run_cost.py --rounds 1 --patch --image <사진> --yes      # 나머지 두 이음매까지
python run_cost.py --case 수치_공백 --rounds 5 --guardrail both --yes
```

- **`--yes` 없이는 돌지 않습니다.** 기본 회차도 1 입니다 - 오타 한 번이 그대로 청구되지 않게.
- 사진은 어떤 이미지든 됩니다. 이미지 입력 토큰은 내용이 아니라 **해상도**로 정해지므로,
  단가 측정에는 같은 해상도의 합성 이미지로 충분합니다.
- `runs/` 는 저장소가 무시합니다. **요약을 RESULTS.md 로 옮기지 않으면 사라집니다.**
