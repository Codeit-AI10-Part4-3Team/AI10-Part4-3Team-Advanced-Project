"""Score generated images for "does it contain text", by script rather than by eye.

Every text-leakage number in RESULTS.md and PIPELINE_SURVEY.md so far came from one
person looking at images. That is not reproducible, and the quality rule in AGENTS.md
asks for a script. This is that script.

Detection only, not recognition: the glyphs these models draw are mostly not real
words, so asking an OCR engine what it *says* is meaningless. What matters is whether
a text detector fires at all, which is exactly the property "no text in the image".

Runs on CPU so it does not contend with generation for the single GPU.

Calibration matters more than the raw number: run it over a set that has already been
judged by eye and compare, before trusting it on a new set.
"""

import argparse
import json
from pathlib import Path

import easyocr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    # 0.05, not the usual 0.3: calibrated against visual judgement over 40 images
    # (PIPELINE_SURVEY 4.6). At 0.3 the detector misses faint package text, which is
    # the wrong direction for a guardrail.
    ap.add_argument("--min-conf", type=float, default=0.05,
                    help="boxes below this confidence are treated as noise")
    args = ap.parse_args()

    reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    results = []
    for d in args.dirs:
        for path in sorted(d.glob("*.png")):
            found = reader.readtext(str(path))
            boxes = [(t, float(c)) for _, t, c in found if c >= args.min_conf]
            results.append({
                "file": str(path),
                "has_text": bool(boxes),
                "n_boxes": len(boxes),
                "top": sorted(boxes, key=lambda b: -b[1])[:3],
            })
            print(f"{'TEXT' if boxes else 'clean'}  {path.name}  ({len(boxes)} boxes)",
                  flush=True)

    clean = sum(1 for r in results if not r["has_text"])
    summary = {"total": len(results), "clean": clean,
               "clean_rate": round(clean / len(results), 3) if results else None,
               "min_conf": args.min_conf, "results": results}
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nclean {clean}/{len(results)}")


if __name__ == "__main__":
    main()
