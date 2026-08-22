"""블라인드 판정 시트 생성과 집계.

기획서 15절: 결과물을 만든 사람이 자기 결과물을 채점하지 않습니다. 이 스크립트는 실험을 돌린
사람이 아닌 판정자에게 넘길 시트를 만들고, 채워진 시트를 B-16 기준으로 집계합니다.

    python score_sheet.py build --run-dir runs/20260813-2010-main --judges 정승호 임동규 송기하
    python score_sheet.py tally --run-dir runs/20260813-2010-main

`--task` 로 판정 종류를 고릅니다 - `text`(1순위 대사 표기), `consistency`(3순위 인물과 화풍
일관성), `style`(5순위 화풍 반영). 셋은 시트의 열이 서로 다르고 파일 이름도 갈라 두었습니다.
같은 회차 폴더를 다시 쓰는 설계라 이름이 같으면 이미 채워진 판정을 덮어씁니다.

`build`가 만드는 시트에는 프롬프트도 조건도 들어가지 않습니다. 판정자가 "무엇이 나와야 하는지"를
먼저 읽으면 없는 글자를 있다고 읽습니다 - 정답 대사는 시트에 들어가지만 어느 쪽이 본안이고
예비안인지는 파일 이름 밖으로 드러내지 않습니다.
"""

from __future__ import annotations

import argparse
import re
import csv
from pathlib import Path
from typing import NamedTuple

import conditions

SHEET_PREFIX = "sheet"

HEAD_COLUMNS = ["회차", "이미지 파일"]
MEMO_COLUMN = "메모"
"""모든 시트가 공유하는 앞뒤 열. 가운데 열만 판정 종류에 따라 갈립니다.

⚠️ **집계가 위치로 읽습니다** (`_parse_sheet`). 세 번째 열이 점수, 네 번째가 보조 판정이므로
앞에 열을 끼우면 판정이 통째로 집계에서 빠집니다.
"""

STATE_COLUMN = "장면 상태 연속 (Y/N)"
"""3순위 시트에만 있는 다섯 번째 열 (2026-08-20 추가, 미결정_대장 A-4).

⚠️ **이 축에는 아직 합격 기준이 없습니다.** B-16 이 확정한 3순위 기준은 "판정자 3명 중 2명
이상이 동일 인물로 판정"뿐이고(기획서 15절), 여기에 기준을 새로 만드는 것은 회의 몫입니다.
그래서 집계는 이 열을 **따로 세어 보여 주기만 하고 합격 판정에 넣지 않습니다** - 넣으면 코드가
회의록 없이 판정 기준을 바꾼 것이 됩니다.
"""

# ⚠️ 3순위 시트를 같은 이름으로 쓰면 **이미 채워진 1순위 판정을 덮어씁니다.** 같은 회차
# 폴더를 다시 쓰는 설계라(3순위는 1순위 이미지를 그대로 봅니다) 이름을 갈라 두어야 합니다.
TASK_PREFIX = {"text": SHEET_PREFIX, "consistency": "consistency", "style": "style"}

STYLE_COLUMN = "지정 화풍"
"""5순위 시트의 네 번째 열. 판정자가 채우는 칸이 아니라 **미리 채워진 기준**입니다.

manifest 의 `art_style_id` 를 행마다 그대로 옮깁니다. 머리말에 한 줄로 적지 않는 이유는
`single_len` 의 정답 카피와 같습니다 -- 회차마다 화풍이 다르므로, 한 줄로 적으면 판정자가 전
회차를 그 화풍 기준으로 채점합니다.
"""

STYLE_CRITERION = (
    "각 회차의 그림이 **그 행에 적힌 화풍으로 보이는지** 봅니다. 그림체, 선, 채색, 질감이 "
    "기준입니다.\n\n"
    "⚠️ **회차마다 지정 화풍이 다릅니다.** 표의 `지정 화풍` 열을 보고 채점하세요. 머리말에 "
    "적힌 화풍 하나로 전 회차를 채점하면 이 실험은 성립하지 않습니다.\n\n"
    "- 그 화풍이라고 볼 수 있으면 `1`, 아니면 `0` 입니다.\n"
    "- **잘 그렸는지를 묻는 것이 아닙니다.** 그림이 마음에 들지 않아도 지정한 화풍으로 "
    "보이면 `1` 입니다.\n"
    "- **대사와 카피의 오탈자는 이 판정과 무관합니다.** 그것은 1순위가 따로 봅니다.\n"
)
"""5순위(화풍 반영)가 묻는 것. 기획서 15절의 완료 판정 기준은 "화풍별 결과가 구분 가능할 것".

⚠️ **화풍 이름을 가리지 않습니다.** 물음이 "지정한 화풍이 결과에 반영됐는가"라 가리면 물어볼
것이 없어집니다. 3순위에서 조건을 가린 것과 다릅니다 -- 그쪽은 "무엇이 나와야 하는지"를 알면
없는 것을 있다고 읽지만, 여기서는 지정값이 곧 물음입니다.
"""

STYLE_DISTINCT_QUESTION = (
    "## 구분되지 않는 화풍이 있습니까\n"
    "\n"
    "위 표는 회차를 **하나씩** 봅니다. 그것만으로는 잡히지 않는 것이 하나 있습니다 -- 두 화풍이 "
    "각각 자기 이름에 맞아 보이는데 **서로는 닮은** 경우입니다. 그러면 표는 전부 `1` 인데 "
    "사용자에게는 선택지가 두 개가 아니라 하나입니다.\n"
    "\n"
    "실제로 나온 지적입니다. 화풍 예시 판정(2026-08-22)에서 두 분이 독립적으로 1번과 2번이 "
    "비슷하다고 적었습니다.\n"
    "\n"
    "서로 구분되지 않는 쌍이 있으면 적어 주세요 (예: `3번과 7번`). 없으면 `없음`.\n"
    "\n"
    "\n"
)
"""시트 말미의 자유 응답. **자동 집계하지 않습니다.**

⚠️ 회차별 Y/N 로는 "두 화풍이 서로 닮았다"가 구조적으로 안 잡힙니다 -- 각 회차가 독립으로
채점되기 때문입니다. 그런데 기획서 15절이 5순위에 건 기준은 "화풍별 결과가 **구분 가능**할
것"이라 이 축이 빠지면 기준의 절반만 재게 됩니다. 답이 자유 문장이라 눈으로 읽습니다.
"""

LENGTH_VARIANTS = frozenset({"mid", "panels_mid"})
"""칸마다 대사 길이가 다른 회차. 길이별 집계(N18)가 붙는 회차이기도 합니다.

`mid` 는 한 장에 6칸을 그린 조건이고 `panels_mid` 는 칸을 따로 생성해 합성한 조건입니다.
**판정 방식은 같지만 결론은 섞으면 안 됩니다** - 운영 경로는 후자뿐입니다 (ADR-0017).
"""


def _read_manifest(run_dir: Path) -> list[dict[str, str]]:
    # ⚠️ 컷별 회차(`run_panels.py`)는 manifest.csv 가 **호출 단위**라 한 세트가 6행입니다.
    # 판정 대상은 합성된 세트 이미지 한 장이므로 그쪽이 남긴 sets.csv 를 먼저 봅니다.
    # 이 순서를 뒤집으면 판정자가 칸 낱장을 세트로 알고 6배를 채점하게 됩니다.
    manifest = run_dir / "sets.csv"
    if not manifest.exists():
        manifest = run_dir / "manifest.csv"
    if not manifest.exists():
        raise SystemExit(f"{manifest}가 없습니다. run_experiment.py를 먼저 돌리세요.")
    with manifest.open(encoding="utf-8") as fp:
        rows = [row for row in csv.DictReader(fp) if row.get("image_file")]
    if not rows:
        raise SystemExit("성공한 회차가 없습니다. manifest.csv의 error 열을 보세요.")
    return rows


def _variant_of(run_dir: Path, rows: list[dict[str, str]]) -> str:
    return rows[0].get("variant") or run_dir.name.rsplit("-", 1)[-1]


def _prefilled_side(task: str, variant: str, row: dict[str, str]) -> str:
    """네 번째 칸을 미리 채우는 판정만 값을 돌려줍니다. 나머지는 판정자 몫이라 빈 칸입니다.

    ⚠️ **회차마다 기준이 다른 판정만 여기 해당합니다** - 5순위는 화풍이, `single_len` 은 정답
    카피가 회차마다 다릅니다. 그 값을 머리말에 한 줄로 적으면 판정자가 전 회차를 그 하나를
    기준으로 채점합니다.
    """
    if task == "style":
        return f"`{row.get('art_style_id', '')}`"
    if variant == "single_len" and row.get("copy"):
        return f"`{row['copy']}`"
    return ""


def _build(run_dir: Path, judges: list[str], task: str = "text") -> None:
    rows = _read_manifest(run_dir)
    variant = _variant_of(run_dir, rows)

    if task == "style":
        # 검증 5순위. 회차마다 **다른 화풍**으로 돌린 결과를 봅니다 (기획서 15절 5번).
        #
        # ⚠️ `art_style_id` 가 빈 회차가 하나라도 있으면 여기서 멈춥니다. 그 회차는 시트의
        # `지정 화풍` 칸이 비고, 판정자는 무엇과 대조할지 모르는 채로 채점하게 됩니다 -
        # 조용히 빈 칸을 내보내는 것보다 여기서 실패하는 편이 낫습니다.
        #
        # ⚠️ **열 존재 여부가 아니라 행마다 봅니다.** 열은 있는데 일부 회차만 비는 경우
        # (손으로 일부만 채웠거나 하네스가 특정 회차를 못 채운 경우)가 실제로 위험한 쪽인데,
        # 열만 확인하면 그것이 통과합니다.
        missing = [row.get("run_id", "?") for row in rows if not row.get("art_style_id")]
        if missing:
            raise SystemExit(
                f"art_style_id 가 비어 있는 회차가 있습니다: {missing}. 5순위는 회차마다 "
                "화풍이 달라야 성립하므로, 화풍을 실어 돌리는 하네스로 회차를 먼저 만드세요."
            )
        criterion = STYLE_CRITERION
        count_column = "지정 화풍 반영 (1) / 아님 (0)"
        count_hint = "그 화풍으로 보이면 `1`, 아니면 `0`"
        # ⚠️ `single_len` 의 정답 카피와 같은 자리(네 번째)입니다. 집계가 세 번째 열을 점수로
        # 읽으므로 앞에 끼우면 판정이 통째로 빠집니다.
        columns = [*HEAD_COLUMNS, count_column, STYLE_COLUMN, MEMO_COLUMN]
    elif task == "consistency":
        # 검증 3순위. 1순위에서 만든 이미지를 그대로 다시 봅니다 - 같은 조건에서 나온 그림이라
        # 새로 생성할 이유가 없고, 생성하면 조건이 달라져 1순위 결과와 이어 붙일 수 없습니다.
        #
        # ⚠️ 세 번째 축(장면 상태)은 2026-08-20 에 추가됐습니다. 그 전 시트는 인물과 화풍만
        # 물었는데, N18 회차에서 판정자 두 분이 **묻지 않은 것을 메모에 적어** 문제가 드러났습니다
        # (미결정_대장 A-4). 묻지 않으면 통과가 나오는데 결과물은 앞뒤가 맞지 않습니다.
        criterion = (
            "**한 장 안에서** 세 가지를 봅니다. 회차끼리 비교하지 마세요.\n\n"
            "1. **같은 인물인가** - 1번부터 5번 칸에 나오는 사람이 같은 사람으로 보이는지. "
            "얼굴, 머리 모양, 복장이 기준입니다. 6번 칸은 제품 컷이라 제외합니다.\n"
            "2. **화풍이 일관되는가** - 6칸이 같은 그림체인지. 한 칸만 사진처럼 나오거나 "
            "다른 톤이면 실패입니다.\n"
            "3. **장면의 상태가 이어지는가** - 앞 칸에서 일어난 일이 뒤 칸에 반영되어 있는지. "
            "이야기를 1번부터 6번까지 순서대로 읽었을 때 앞뒤가 맞아야 합니다.\n\n"
            "   3번은 **인물이 같은지와 다른 질문입니다.** 같은 사람이 같은 그림체로 나와도 "
            "장면이 되돌아갈 수 있습니다. 실제로 나온 사례가 이렇습니다.\n\n"
            "   - 3번 칸에서 닦아낸 커피가 6번 칸에 다시 쏟아져 있음\n"
            "   - 아이가 등장한 뒤 책상 길이가 짧아짐\n"
            "   - 앞 칸에서 꺼낸 물건이 뒤 칸에서 다시 제자리에 있음\n\n"
            "   되돌아가거나 사라지거나 갑자기 생긴 것이 하나라도 있으면 `N` 입니다.\n"
        )
        count_column = "동일 인물 (1) / 아님 (0)"
        count_hint = "1번부터 5번 칸이 같은 사람으로 보이면 `1`, 아니면 `0`"
        columns = [
            *HEAD_COLUMNS,
            count_column,
            "6칸 화풍 일관 (Y/N)",
            STATE_COLUMN,
            MEMO_COLUMN,
        ]
    elif variant in ("single", "single_len"):
        # 단일 광고형은 칸이 없습니다. 6칸 척도를 그대로 쓰면 판정자가 없는 칸을 세게 됩니다.
        #
        # ⚠️ `single_len` 은 **회차마다 카피가 다릅니다.** 정답을 머리말에 한 줄로 적으면
        # 판정자가 전 회차를 그 문장 기준으로 채점하게 되므로, 표의 각 행에 정답을 붙입니다.
        per_row_answer = variant == "single_len"
        if per_row_answer:
            criterion = (
                "이미지에 그려진 한국어 카피가 **그 행의 정답과 글자 단위로 완전히 같은지** "
                "봅니다. 한 글자라도 다르거나, 빠지거나, 깨져 있으면 실패입니다. 정답에 없는 "
                "문구가 추가로 그려져 있어도 실패입니다.\n\n"
                "⚠️ **회차마다 정답이 다릅니다.** 표의 `정답 카피` 열을 보고 채점하세요.\n"
            )
        else:
            criterion = (
                "이미지에 그려진 한국어 카피가 아래 정답과 **글자 단위로 완전히 같은지** 봅니다. "
                "한 글자라도 다르거나, 빠지거나, 깨져 있으면 실패입니다. 정답에 없는 문구가 "
                "이미지에 추가로 그려져 있어도 실패입니다 (근거에 없는 문구를 넣지 말라고 "
                "지시했습니다).\n\n"
                f"- 카피: `{conditions.SINGLE_AD_COPY}`\n"
            )
        count_column = "카피 정확 (1) / 실패 (0)"
        count_hint = "정확하면 `1`, 한 글자라도 어긋나거나 없는 문구가 추가됐으면 `0`"
        # ⚠️ 정답 카피를 세 번째가 아니라 네 번째 열에 둡니다. 집계(`_parse_sheet`)가 세 번째
        # 열을 점수로 읽으므로, 정답을 앞에 끼우면 판정이 통째로 집계에서 빠집니다.
        side_column = "정답 카피" if per_row_answer else "제품이 주인공 (Y/N)"
        columns = [*HEAD_COLUMNS, count_column, side_column, MEMO_COLUMN]
    elif variant in ("main", "hard", "mid", "panels_base", "panels_mid"):
        # 어려운 대사 회차는 정답 문자열만 다르고 척도는 같습니다. 정답 표를 갈아 끼우지
        # 않으면 판정자가 1순위 대사를 기준으로 채점하게 됩니다.
        panels = {
            "hard": conditions.PANELS_HARD,
            "mid": conditions.PANELS_MID,
            "panels_mid": conditions.PANELS_MID,
        }.get(variant, conditions.PANELS)
        answer_block = "\n".join(f"- {p.index}번 칸: `{p.line}`" for p in panels)
        criterion = (
            "각 칸의 말풍선 글자가 아래 정답과 **글자 단위로 완전히 같은지** 봅니다. "
            "한 글자라도 다르거나, 빠지거나, 깨져 있으면 그 칸은 오탈자입니다.\n\n"
            f"{answer_block}\n"
        )
        count_column = "오탈자 없는 칸 수 (0-6)"
        count_hint = "여섯 칸 모두 정확하면 `6`, 한 칸만 틀렸으면 `5`"
        if variant in LENGTH_VARIANTS:
            # ⚠️ N18 은 "몇 칸이 틀렸는가"가 아니라 **"몇 자부터 틀리는가"**를 묻습니다.
            # 칸마다 대사 길이가 다르므로 틀린 칸 번호가 없으면 길이별 집계가 성립하지 않고,
            # 그러면 회차를 몇 번 돌려도 상한을 못 정합니다.
            #
            # ⚠️ 시트에 길이를 적지 않습니다. "이게 제일 긴 대사"라고 알려 주면 판정이
            # 그쪽으로 끌립니다. 길이는 집계할 때 칸 번호로 되붙입니다.
            columns = [*HEAD_COLUMNS, count_column, "틀린 칸 번호 (쉼표)", MEMO_COLUMN]
        else:
            columns = [*HEAD_COLUMNS, count_column, "6칸 균등 분할 (Y/N)", MEMO_COLUMN]
    else:
        criterion = (
            "각 칸에 말풍선이 있고 그 안이 **비어 있는지** 봅니다. 글자처럼 보이는 것이 하나라도 "
            "그려져 있으면 그 칸은 실패입니다 (예비안은 글자를 나중에 합성합니다).\n"
        )
        count_column = "빈 말풍선 칸 수 (0-6)"
        count_hint = "여섯 칸 모두 비어 있으면 `6`, 한 칸에 글자가 보이면 `5`"
        columns = [*HEAD_COLUMNS, count_column, "6칸 균등 분할 (Y/N)", MEMO_COLUMN]

    # 마지막 항목만 판정 종류마다 갈립니다. 앞의 세 줄은 어느 시트에나 같습니다.
    #
    # ⚠️ 문자열을 조립한 뒤 잘라 붙이지 않습니다. 전에는 `rsplit` 으로 마지막 항목을 떼어
    # 냈는데, 그 방식은 떼어 낼 문장이 한 글자만 바뀌어도 **조용히 두 문단이 겹쳐 남습니다.**
    tail = f"- 나머지 두 열({columns[3]}, {MEMO_COLUMN})은 참고용입니다. 비어 있어도 판정은 성립합니다."
    if task == "consistency":
        # ⚠️ 여기서는 다섯 번째 열이 참고용이 아닙니다. **묻지 않으면 안 보는 축**이라서
        # 이 시트를 고친 것이고(A-4), "비어 있어도 성립한다"고 읽히면 고친 의미가 없습니다.
        tail = (
            f"- **`{STATE_COLUMN}` 열도 반드시 채워 주세요.** 인물과 화풍이 멀쩡해도 장면이 "
            "되돌아가는 사례가 실제로 나왔습니다. 앞의 두 열만 보면 그런 회차가 통과로 "
            "집계됩니다.\n"
            f"- `{columns[3]}` 는 참고용입니다.\n"
            "- **`N` 을 적으셨으면 메모에 어느 칸인지 적어 주세요** (예: `6번 칸에서 커피가 "
            "다시 쏟아짐`). 몇 번째 칸에서 어긋나는지가 원인 판단의 근거입니다."
        )
    elif task == "style":
        # `지정 화풍` 도 이미 채워져 있는 기준입니다 (`정답 카피` 와 같은 이유).
        tail = (
            f"- **`{STYLE_COLUMN}` 열은 이미 채워져 있습니다.** 회차마다 화풍이 다르니 그 행의 "
            "값과 대조하세요. 고치지 마세요.\n"
            "- **시트 맨 아래의 `구분되지 않는 화풍이 있습니까` 도 채워 주세요.** 표만으로는 "
            "두 화풍이 서로 닮았는지가 잡히지 않습니다.\n"
            "- **`0` 을 적으셨으면 메모에 무엇이 달랐는지 적어 주세요** (예: `사진처럼 나옴`). "
            "화풍 문구를 고칠지 판단하는 근거입니다."
        )
    elif variant == "single_len":
        # `정답 카피` 는 판정자가 채우는 칸이 아니라 이미 채워져 있는 기준입니다. 기본 문장을
        # 그대로 두면 "비워도 되는 칸"으로 읽힙니다.
        tail = (
            "- **`정답 카피` 열은 이미 채워져 있습니다.** 회차마다 정답이 다르니 그 행의 "
            "문장과 대조하세요. 고치지 마세요.\n"
            "- 메모는 참고용입니다. 틀린 글자를 적어 주시면 더 좋습니다."
        )
    elif variant in LENGTH_VARIANTS:
        # ⚠️ 이 회차에서는 네 번째 열이 참고용이 아닙니다. 칸마다 대사 길이가 달라서
        # **어느 칸이 틀렸는지가 곧 어느 길이가 틀렸는지**이고, 그것이 이 실험의 목적입니다
        # (N18). 기본 문장을 그대로 두면 판정자가 비워도 된다고 읽습니다.
        tail = (
            f"- **`{columns[3]}` 열도 함께 채워 주세요.** 칸 수만 있으면 몇 칸이 틀렸는지는 "
            "알아도 **어느 칸이 틀렸는지**를 알 수 없고, 이번 실험은 그것을 재는 것입니다. "
            "틀린 칸이 없으면 비워 두세요.\n"
            "- 메모는 참고용입니다. 틀린 글자를 적어 주시면 더 좋습니다."
        )

    # ⚠️ 이 안내가 없던 1차 회차에서 판정자 한 명이 세 번째 열을 통째로 비워, 그분의 판정이
    # 집계에서 빠졌습니다(총평에는 결론이 적혀 있었는데도). 열의 의미를 시트 안에서 못 읽으면
    # 메모만 채우게 됩니다.
    how_to_fill = (
        "## 어떻게 채우는가\n\n"
        f"- **`{count_column}` 열이 이 판정의 본체입니다.** 숫자를 적으세요 - "
        f"{count_hint}.\n"
        "- **이 열이 비면 그 회차는 집계에서 통째로 빠집니다.** 총평에 결론을 적어도 수치로는 "
        "들어가지 않습니다.\n"
        "- 판단이 서지 않는 회차만 비우고 메모에 이유를 적으세요. 추측으로 채운 값이 근거로 "
        "올라가는 것보다는 낫습니다.\n"
        f"{tail}"
    )

    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"

    for judge in judges:
        lines = [
            f"# 판정 시트 - {run_dir.name} / {judge}",
            "",
            "## 무엇을 보는가",
            "",
            criterion,
            "**이미지를 만든 사람은 이 시트를 채우지 않습니다.**",
            "",
            how_to_fill,
            "",
            "## 채점",
            "",
            header,
            divider,
        ]
        for row in rows:
            answer = _prefilled_side(task, variant, row)
            # ⚠️ 칸 수를 `columns` 에서 세어 맞춥니다. 전에는 다섯 칸이 박혀 있었는데, 3순위
            # 시트가 여섯 열이 되면서 **표가 한 칸씩 밀렸습니다** - 마크다운은 모자란 칸을
            # 조용히 비워 두므로 렌더링만 보면 멀쩡해 보이고, 집계에서야 어긋납니다.
            cells = [str(row["run_id"]), f"`{row['image_file']}`", "", answer]
            cells += [""] * (len(columns) - len(cells))
            lines.append("| " + " | ".join(cells) + " |")
        lines += [""]
        if task == "style":
            # 표 다음, 총평 앞입니다. 표를 다 채운 직후에 물어야 회차들이 아직 눈에 남아 있습니다.
            lines.append(STYLE_DISTINCT_QUESTION)
        lines += [
            "## 총평 (한 줄)",
            "",
            "",
        ]
        path = run_dir / f"{TASK_PREFIX[task]}-{judge}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"생성: {path}")

    print(
        "\n판정자에게 시트와 이미지를 함께 넘기세요. 이미지는 커밋하지 말고 팀 공유 드라이브로 "
        "올립니다 (구현_범위 4.3절)."
    )


def _bad_panels(cell: str | None) -> set[int]:
    """"틀린 칸 번호" 칸에서 정수만 뽑습니다. `3, 6` `3 6` `3번,6번` 다 받습니다."""
    if not cell:
        return set()
    return {int(token) for token in re.findall(r"[1-6]", cell)}


def _tally_by_length(sheets: list[Path]) -> None:
    """N18 의 본체 - 길이별 오탈자율.

    ⚠️ **"틀린 칸 번호" 열이 비어 있으면 무오탈자로 셉니다.** 칸 수 열이 6이면 실제로 그렇고,
    6 미만인데 번호가 비면 어느 길이가 틀렸는지 알 수 없으므로 그 회차는 길이 집계에서
    빠집니다 - 회차 수와 길이 표본 수가 다르게 나오면 그것이 이유입니다.

    ⚠️ **두 열이 서로 어긋나는 회차도 뺍니다.** 칸 수 6에 번호가 적혀 있거나, 칸 수 4에 번호가
    하나뿐인 경우입니다. 어느 쪽이 맞는지 알 수 없는데 그대로 세면 없는 실패가 생기거나, 빠진
    칸이 정상 표본으로 들어가 **상한이 실제보다 높게** 잡힙니다.
    """
    by_index = {p.index: len(p.line) for p in conditions.PANELS_MID}
    judges_of_run: dict[int, int] = {}
    flags_of_run: dict[int, dict[int, int]] = {}

    for sheet in sheets:
        for run_id, (panels_ok, cell, _) in _parse_sheet(sheet).items():
            if panels_ok is None:
                continue
            bad = _bad_panels(cell)
            if panels_ok < conditions.PANEL_COUNT and not bad:
                continue  # 틀렸다는데 어느 칸인지 안 적혔습니다
            if len(bad) != conditions.PANEL_COUNT - panels_ok:
                print(
                    f"    주의: {sheet.name} 의 {run_id}번 회차 - 칸 수 {panels_ok}, "
                    f"틀린 칸 {sorted(bad)} - 두 열이 맞지 않아 길이 집계에서 뺍니다"
                )
                continue
            judges_of_run[run_id] = judges_of_run.get(run_id, 0) + 1
            slot = flags_of_run.setdefault(run_id, {})
            for index in bad:
                slot[index] = slot.get(index, 0) + 1

    runs = len(judges_of_run)
    votes = sum(judges_of_run.values())

    print("\n길이별 집계 (N18)")
    print("| 칸 | 길이 | 회차 | 오탈자 회차 | 비율 | 지목/판정 |")
    print("|---|---|---|---|---|---|")
    for index, length in sorted(by_index.items(), key=lambda kv: kv[1]):
        # ⚠️ **판정자 수로 표본을 곱하지 않습니다.** 세 사람이 같은 이미지를 보는 것이라
        # 독립 표본이 아니고, 그대로 세면 5세트가 표본 15로 보여 신뢰도가 3배로 부풀려집니다.
        # 회차 단위로 접고 B-16 의 다수결(3명 중 2명 이상)로 판정합니다.
        flagged = sum(1 for r, c in judges_of_run.items() if flags_of_run.get(r, {}).get(index, 0) * 2 > c)
        picks = sum(slot.get(index, 0) for slot in flags_of_run.values())
        rate = f"{flagged / runs:.0%}" if runs else "-"
        print(f"| {index} | {length}자 | {runs} | {flagged} | {rate} | {picks}/{votes} |")

    print(
        f"\n회차 {runs}건 / 판정 {votes}건. **비율은 회차 기준이고 다수결(과반)로 판정합니다** - "
        "판정자 수를 표본으로 곱하면 신뢰도가 부풀려집니다.\n"
        "`지목/판정` 이 다수결과 어긋나면(예: 지목은 있는데 오탈자 회차가 0) 판정이 갈린 "
        "것이므로, 그 칸은 수치보다 메모를 먼저 보세요.\n"
        "상한은 **오탈자가 처음 나오는 길이의 바로 아래**로 잡되, 회차가 적으면 0건도 안전을 "
        "보증하지 않습니다."
    )


def _parse_sheet(path: Path, *, with_state: bool = False) -> dict[int, tuple[int | None, str | None, str | None]]:
    """채워진 시트에서 (회차 -> (점수, 보조 판정, 장면 상태))를 뽑습니다.

    ⚠️ **다섯 번째 칸은 `with_state` 일 때만 읽습니다.** 1순위 시트는 다섯 열짜리라 그 자리가
    메모이고, 그대로 읽으면 판정자가 쓴 산문이 Y/N 판정으로 집계됩니다. 3순위 시트만 여섯 열
    입니다.
    """
    result: dict[int, tuple[int | None, str | None, str | None]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        panels = int(cells[2]) if cells[2].isdigit() else None
        grid = cells[3].upper() if cells[3] else None
        state = cells[4].upper() if with_state and len(cells) >= 6 and cells[4] else None
        result[int(cells[0])] = (panels, grid, state)
    return result


def _tally_single_lengths(rows: list[dict[str, str]], sheets: list[Path]) -> None:
    """단건 광고형의 길이별 집계.

    만화형과 달리 **한 장이 곧 길이 1표본**입니다. 회차와 길이의 대응은 manifest 의 `copy`
    열에서 읽습니다 - `run_id` 로 다시 계산하면 `--start-id` 가 달라지는 순간 어긋납니다.
    """
    length_of = {int(r["run_id"]): len(r.get("copy") or "") for r in rows if r.get("copy")}
    if not length_of:
        print("\n길이별 집계: manifest 에 copy 열이 없습니다 (옛 회차)")
        return

    # ⚠️ 만화형과 같은 이유로 판정자 수를 표본으로 곱하지 않습니다. 회차 단위로 접고
    # 다수결(과반)로 판정하며, 갈린 판정은 `지목/판정` 으로 드러냅니다.
    judges: dict[int, int] = {}
    picks: dict[int, int] = {}
    for sheet in sheets:
        for run_id, (score, _, _unused) in _parse_sheet(sheet).items():
            if score is None or run_id not in length_of:
                continue
            judges[run_id] = judges.get(run_id, 0) + 1
            if score < 1:
                picks[run_id] = picks.get(run_id, 0) + 1

    print("\n길이별 집계 (단건 광고형)")
    print("| 길이 | 회차 | 실패 회차 | 지목/판정 |")
    print("|---|---|---|---|")
    for run_id in sorted(judges, key=lambda r: length_of[r]):
        n = judges[run_id]
        pick = picks.get(run_id, 0)
        verdict = "실패" if pick * 2 > n else "통과"
        print(f"| {length_of[run_id]}자 | 1 | {verdict} | {pick}/{n} |")
    print(
        "\n⚠️ **길이당 회차가 1건입니다.** 이 회차는 경계 탐색이 아니라 **만화형 상한을 단건에 "
        "그대로 써도 되는지 보는 대조군**입니다. 한 건의 통과가 그 길이의 안전을 뜻하지 않습니다."
    )

def _report_state(
    filled: dict[int, tuple[int | None, str | None, str | None]], threshold: int
) -> None:
    """3순위의 세 번째 축 (2026-08-20 추가, 미결정_대장 A-4).

    ⚠️ **합격 판정에 넣지 않고 따로 보여 줍니다.** B-16 이 확정한 3순위 기준은 동일 인물
    다수결뿐이고, 여기에 기준을 만드는 것은 회의 몫입니다 (`STATE_COLUMN` 참고).

    ⚠️ 그래서 **인물은 통과인데 상태가 깨진 회차**를 따로 찍습니다. 두 수치를 나란히 두기만
    하면 읽는 사람 눈에는 "3순위 통과"만 남습니다 - 시트를 고친 이유가 그것입니다.
    """
    judged = {run_id: value[2] for run_id, value in filled.items() if value[2]}
    broken = sorted(run_id for run_id, state in judged.items() if state != "Y")
    print(
        f"    장면 상태 연속 - {len(judged) - len(broken)}/{len(judged)}건 "
        f"(판정 안 한 회차 {len(filled) - len(judged)}건)"
    )
    if not broken:
        return
    print(f"    상태가 깨진 회차: {broken}")
    also_ok = [run_id for run_id in broken if (filled[run_id][0] or 0) >= threshold]
    if also_ok:
        print(
            f"    주의: 그중 {also_ok} 는 동일 인물 판정이 통과입니다. "
            "인물만 보면 합격인데 이야기가 앞뒤가 맞지 않는 회차입니다"
        )


def _majority(flags: list[int]) -> bool | None:
    """과반이면 True, 아니면 False. 판정자가 2명 미만이면 `None`.

    ⚠️ **한 명이 본 회차는 다수결이 성립하지 않습니다.** 그대로 세면 1명 통과가 "다수결 통과"로
    올라가는데, B-16 이 요구한 것은 3명 중 2명 이상입니다.
    """
    if len(flags) < 2:
        return None
    return sum(flags) * 2 > len(flags)


def _collect_votes(
    sheets: list[Path],
) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[int, list[int]]]:
    """3순위 시트들을 회차별로 접습니다 - (동일 인물, 화풍 일관, 장면 상태)."""
    same: dict[int, list[int]] = {}
    style: dict[int, list[int]] = {}
    state: dict[int, list[int]] = {}
    for sheet in sheets:
        for run_id, (score, side, scene) in _parse_sheet(sheet, with_state=True).items():
            if score is None:
                continue
            same.setdefault(run_id, []).append(1 if score >= 1 else 0)
            if side:
                style.setdefault(run_id, []).append(1 if side == "Y" else 0)
            if scene:
                state.setdefault(run_id, []).append(1 if scene == "Y" else 0)
    return same, style, state


def _axis_line(label: str, votes: dict[int, list[int]]) -> tuple[str, list[int], list[int]]:
    """한 축의 다수결 결과를 한 줄로 요약하고, 미달 회차와 갈린 회차를 함께 돌려줍니다."""
    verdicts = {run_id: _majority(flags) for run_id, flags in votes.items()}
    decided = {run_id: v for run_id, v in verdicts.items() if v is not None}
    failed = sorted(run_id for run_id, ok in decided.items() if not ok)
    split = sorted(run_id for run_id, flags in votes.items() if 0 < sum(flags) < len(flags))
    passed = len(decided) - len(failed)
    line = f"    {label} - {passed}/{len(decided)}회차 (판정자 과반 기준)"
    if len(verdicts) > len(decided):
        undecided = sorted(run_id for run_id, v in verdicts.items() if v is None)
        line += f", 다수결 미성립 {undecided}"
    return line, failed, split


def _tally_consistency(sheets: list[Path]) -> None:
    """3순위의 합격 판정 - 회차마다 판정자 다수결 (B-16).

    ⚠️ **판정자별 비율은 합격 판정이 아닙니다.** B-16 이 3순위에 건 기준은 "회차마다 판정자
    3명 중 2명 이상이 동일 인물로 판정"이므로, 판정 단위가 판정자가 아니라 **회차**입니다.
    2026-08-21 C2 집계까지는 이 다수결을 코드가 계산하지 않아 손으로 셌습니다.

    ⚠️ **총평(전체 기준 충족 여부)을 코드가 내지 않습니다.** B-16 은 회차별 기준만 정했고
    "몇 회차가 통과해야 과제가 통과인가"는 정한 적이 없습니다. 여기서 임계값을 만들면 코드가
    회의록 없이 판정 기준을 세우는 것이 됩니다 (`STATE_COLUMN` 과 같은 이유).
    """
    same, style, state = _collect_votes(sheets)
    if not same:
        return

    print("\n회차별 다수결 (B-16)")
    line, failed, split = _axis_line("동일 인물 (합격 판정)", same)
    print(line)
    if failed:
        print(f"    기준 미달 회차: {failed}")
    if split:
        print(f"    판정이 갈린 회차: {split} - 수치보다 메모를 먼저 보세요")

    # 아래 두 축은 **참고입니다.** 화풍은 B-16 이 기준을 걸지 않았고, 장면 상태는 2026-08-21
    # 회의가 "이번 범위 제외, 참고 항목으로만"으로 닫았습니다 (미결정_대장 A-4).
    for label, votes in (("화풍 일관 (참고)", style), ("장면 상태 연속 (참고)", state)):
        if not votes:
            continue
        ref_line, ref_failed, _ = _axis_line(label, votes)
        print(ref_line)
        if ref_failed:
            print(f"        어긋난 회차: {ref_failed}")

    # ⚠️ 인물은 통과인데 상태가 깨진 회차를 따로 찍습니다. 두 수치를 나란히 두기만 하면 읽는
    # 사람 눈에는 "3순위 통과"만 남습니다 - 판정 시트에 상태 열을 넣은 이유가 그것입니다.
    hidden = sorted(
        run_id
        for run_id, flags in state.items()
        if _majority(flags) is False and _majority(same.get(run_id, [])) is True
    )
    if hidden:
        print(
            f"    주의: {hidden} 는 인물 판정은 통과인데 장면 상태가 다수결 `N` 입니다 "
            "- 합격 판정에는 영향이 없고 보고서에 관측치로 병기합니다"
        )

    print(
        "    전체 기준 충족 여부는 코드가 적지 않습니다 - B-16 은 회차별 기준만 정했고 "
        "회차 몇 건이 통과해야 하는지는 정한 적이 없습니다."
    )


def _tally_style(rows: list[dict[str, str]], sheets: list[Path]) -> None:
    """5순위의 합격 판정 - 화풍마다 판정자 다수결 (기획서 15절 5번).

    ⚠️ **판정 단위가 회차이자 곧 화풍입니다.** 회차마다 다른 화풍으로 돌린 결과라, 어느 회차가
    미달인지가 곧 어느 화풍이 반영되지 않았는지입니다. 그래서 회차 번호만 찍지 않고 화풍
    이름을 붙입니다 - 번호만으로는 무엇을 고쳐야 하는지 알 수 없습니다.

    ⚠️ **판정자 수로 표본을 곱하지 않습니다.** 세 사람이 같은 이미지를 봅니다 (3순위와 같은
    이유).

    ⚠️ **총평(전체 기준 충족 여부)을 코드가 내지 않습니다.** 기획서 15절이 5순위에 건 것은
    "화풍별 결과가 구분 가능할 것. 판정자 3명 중 2명 이상"이고, **8종 중 몇 종이 통과해야
    과제가 통과인지는 정한 적이 없습니다.** 여기서 임계값을 만들면 코드가 회의록 없이 판정
    기준을 세우는 것이 됩니다 (`STATE_COLUMN` 과 같은 이유).
    """
    style_of = {int(r["run_id"]): r.get("art_style_id", "") for r in rows if r.get("run_id")}

    votes: dict[int, list[int]] = {}
    for sheet in sheets:
        for run_id, (score, _side, _state) in _parse_sheet(sheet).items():
            if score is None:
                continue
            votes.setdefault(run_id, []).append(1 if score >= 1 else 0)
    if not votes:
        return

    print("\n화풍별 다수결 (기획서 15절 5번)")
    print("| 회차 | 지정 화풍 | 반영 판정 | 찬성/판정 |")
    print("|---|---|---|---|")
    undecided: list[int] = []
    for run_id in sorted(votes):
        flags = votes[run_id]
        verdict = _majority(flags)
        if verdict is None:
            undecided.append(run_id)
            label = "다수결 미성립"
        else:
            label = "반영" if verdict else "**미달**"
        print(f"| {run_id} | {style_of.get(run_id, '')} | {label} | {sum(flags)}/{len(flags)} |")

    if undecided:
        print(f"    다수결 미성립 회차: {undecided} - 판정자가 2명 미만입니다")
    split = sorted(r for r, flags in votes.items() if 0 < sum(flags) < len(flags))
    if split:
        print(f"    판정이 갈린 회차: {split} - 수치보다 메모를 먼저 보세요")

    print(
        "\n    **`구분되지 않는 화풍이 있습니까` 는 집계하지 않습니다.** 회차별 Y/N 로는 두 "
        "화풍이 서로 닮았는지가 구조적으로 안 잡히는데, 기준의 절반이 그것입니다. 시트 말미의 "
        "자유 응답을 직접 읽으세요.\n"
        "    전체 기준 충족 여부도 코드가 적지 않습니다 - 기획서 15절은 회차별 기준만 정했고 "
        "8종 중 몇 종이 통과해야 하는지는 정한 적이 없습니다."
    )


class Axis(NamedTuple):
    """판정 종류마다 갈리는 세 값 - 합격 문턱, 본체 열 이름, 보조 열 이름."""

    threshold: int
    scale: str
    side_label: str


def _axis_of(task: str, variant: str) -> Axis:
    # 단일 광고형은 칸이 없어 척도가 0/1 입니다. 6칸 기준을 그대로 적용하면 정확한 회차가
    # 전부 실패로 집계됩니다.
    if task == "style":
        return Axis(1, "지정 화풍 반영", STYLE_COLUMN)
    if task == "consistency":
        return Axis(1, "동일 인물 판정", "6칸 화풍 일관")
    if variant in ("single", "single_len"):
        side = "정답 카피" if variant == "single_len" else "제품이 주인공"
        return Axis(1, "카피 정확", side)
    return Axis(
        conditions.PANELS_OK_THRESHOLD,
        f"{conditions.PANELS_OK_THRESHOLD}칸 이상",
        "틀린 칸 번호" if variant in LENGTH_VARIANTS else "6칸 균등 분할",
    )


def _report_judge(sheet: Path, prefix: str, task: str, variant: str, total: int, axis: Axis) -> None:
    """판정자 한 사람의 시트를 요약합니다.

    ⚠️ 3순위에서 여기 나오는 수치는 **판정자 개인 값이지 합격 판정이 아닙니다.** B-16 의
    3순위 기준은 회차별 다수결이고 그것은 `_tally_consistency` 가 냅니다.
    """
    judge = sheet.stem[len(prefix) + 1 :]
    scored = _parse_sheet(sheet, with_state=task == "consistency")
    filled = {k: v for k, v in scored.items() if v[0] is not None}
    if not filled:
        print(f"- {judge}: 채워진 칸이 없습니다 (건너뜀)")
        return

    ok_runs = sum(1 for panels, _, _s in filled.values() if panels >= axis.threshold)
    rate = ok_runs / len(filled)
    side_ok = sum(1 for _, grid, _s in filled.values() if grid == "Y")
    side_rate = side_ok / len(filled)
    # ⚠️ **`task` 를 `variant` 보다 먼저 봅니다.** 3순위는 1순위와 같은 회차 폴더를 쓰므로
    # `variant` 가 `panels_mid` 인 채로 들어옵니다. 순서를 뒤집으면 3순위 시트의 네 번째
    # 열(화풍 Y/N)이 "칸 번호" 로 취급돼 참고치가 0 으로 눌립니다 (2026-08-20 발견).
    numeric_side = task == "text" and variant in LENGTH_VARIANTS
    if numeric_side:
        side_ok = side_rate = 0.0  # 이 열은 Y/N 이 아니라 칸 번호입니다 (아래에서 집계)

    print(f"- {judge}: 판정 {len(filled)}/{total}건")
    if task in ("consistency", "style"):
        # ⚠️ 여기서는 **비율도 기준도 적지 않습니다.** 1순위의 80%를 붙이면 판정자 한 사람이
        # 통과와 미달을 가르는 것처럼 보입니다.
        print(f"    {axis.scale} {ok_runs}건 (판정자 개인 수치. 합격 판정은 아래 다수결)")
    else:
        print(
            f"    성공 판정 - {axis.scale} {ok_runs}건 "
            f"= {rate:.0%} (기준 {conditions.PASS_RATE_THRESHOLD:.0%})"
        )
    # ⚠️ 5순위의 네 번째 열은 Y/N 이 아니라 **미리 채워진 화풍 이름**입니다 (`single_len` 의
    # 정답 카피와 같습니다). 그대로 세면 참고치가 언제나 0건 = 0% 로 찍혀, 읽는 사람에게는
    # "화풍이 하나도 안 맞았다"로 보입니다.
    if not numeric_side and variant != "single_len" and task != "style":
        print(f"    참고 - {axis.side_label} {side_ok}건 = {side_rate:.0%}")

    if task == "consistency":
        _report_state(filled, axis.threshold)
    elif task == "style":
        # ⚠️ 1순위의 회차 수 기준(`TARGET_RUNS` = 20)을 걸지 않습니다. 5순위의 회차 수는
        # 화풍 종 수(8)에서 나오므로, 그 기준을 붙이면 8종 전부 통과해도 "확정 판정이
        # 아닙니다"가 찍힙니다. 합격 판정은 아래 다수결이 냅니다.
        pass
    elif len(filled) < conditions.TARGET_RUNS:
        # ⚠️ 이 두 값은 1순위 전용입니다 (conditions.py 주석). 3순위에 걸면 12회차
        # 만장일치가 "확정 판정이 아닙니다"로 찍힙니다.
        print(f"    주의: 회차가 {conditions.TARGET_RUNS}회에 못 미쳐 확정 판정이 아닙니다")
    else:
        verdict = "기준 충족" if rate >= conditions.PASS_RATE_THRESHOLD else "기준 미달"
        print(f"    판정: {verdict}")


def _tally(run_dir: Path, task: str = "text") -> None:
    rows = _read_manifest(run_dir)
    variant = _variant_of(run_dir, rows)
    prefix = TASK_PREFIX[task]
    sheets = sorted(run_dir.glob(f"{prefix}-*.md"))
    if not sheets:
        raise SystemExit("채워진 판정 시트가 없습니다. build를 먼저 돌리고 판정을 받으세요.")

    total = len(rows)
    print(f"회차 {total}건 / 판정자 {len(sheets)}명 / variant={variant}\n")
    axis = _axis_of(task, variant)

    for sheet in sheets:
        _report_judge(sheet, prefix, task, variant, total, axis)

    if task == "consistency":
        _tally_consistency(sheets)
    elif task == "style":
        _tally_style(rows, sheets)

    # ⚠️ 길이별 집계는 **1순위 시트에만** 붙습니다. 3순위는 같은 회차 폴더를 쓰지만 시트의
    # 열이 다르므로, 그대로 돌리면 전부 0 인 N18 표가 딸려 나옵니다 - 읽는 사람에게는
    # "길이 실험 결과가 0건" 으로 보입니다 (2026-08-20 발견).
    if task == "text":
        if variant in LENGTH_VARIANTS:
            _tally_by_length(sheets)
        if variant == "single_len":
            _tally_single_lengths(rows, sheets)

    # 옮겨 적을 자리가 판정마다 다릅니다. A-1 을 그대로 찍으면 5순위 수치가 1순위 항목으로
    # 올라갑니다 - 대장은 항목마다 근거가 다른 문서라 그 한 줄이 근거를 어긋나게 만듭니다.
    destination = {
        "text": "미결정_대장(A-1)",
        "consistency": "미결정_대장(A-4)",
        "style": "미결정_대장(A-3)과 검증 5순위 보고서",
    }[task]
    print(
        f"\n수치는 회의록과 {destination}에 옮기세요. 시트와 이미지는 커밋되지 않으므로 "
        "여기에만 두면 없었던 실험이 됩니다 (구현_범위 4.3절)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="판정 시트 생성")
    build.add_argument("--run-dir", type=Path, required=True)
    build.add_argument("--judges", nargs="+", required=True, help="실험을 돌린 사람은 제외")
    build.add_argument(
        "--task",
        choices=["text", "consistency", "style"],
        default="text",
        help="text=대사 표기(1순위), consistency=캐릭터와 화풍 일관성(3순위), "
        "style=화풍 반영(5순위). 3순위는 1순위 이미지를 그대로 다시 보므로 추가 생성이 "
        "없습니다. 5순위는 회차마다 화풍이 달라야 하므로 전용 회차가 필요합니다",
    )

    tally = sub.add_parser("tally", help="채워진 시트 집계")
    tally.add_argument("--run-dir", type=Path, required=True)
    tally.add_argument("--task", choices=["text", "consistency", "style"], default="text")

    args = parser.parse_args()
    if args.command == "build":
        _build(args.run_dir, args.judges, args.task)
    else:
        _tally(args.run_dir, args.task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
