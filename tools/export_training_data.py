"""把评测存档导出为 SFT / DPO 训练数据。

用法：
    uv run python tools/export_training_data.py --round-dir eval/archive/2026-08-15/round-1

规则：
    - SFT：score>=4.5 且 judgement=correct 且 grounding>=4
    - DPO：同一题同时存在 good/bad 回答时，组成 chosen/rejected 偏好对
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "eval" / "samples" / "golden_set.jsonl"


def load_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _is_good(row: dict) -> bool:
    return (
        row.get("score", 0) >= 4.5
        and row.get("judgement") == "correct"
        and (row.get("scores") or {}).get("grounding", 0) >= 4
    )


def _is_bad(row: dict) -> bool:
    return row.get("score", 0) <= 2 or (row.get("scores") or {}).get("grounding", 0) <= 2


def export(round_dir: Path, out_dir: Path, samples_path: Path) -> dict:
    answers = {a["id"]: a for a in load_jsonl(round_dir / "answers.jsonl")}
    judged = load_jsonl(round_dir / "judged.jsonl")
    samples = {s["id"]: s for s in load_jsonl(samples_path)}
    sft = []
    pairs: dict[str, dict] = {}
    for row in judged:
        sample = samples.get(row.get("id"))
        answer = answers.get(row.get("id"))
        if not sample or not answer:
            continue
        question = (sample.get("payload") or {}).get("user_question", "")
        instruction = {
            "instruction": question,
            "input": json.dumps(sample.get("payload", {}), ensure_ascii=False),
            "output": answer.get("answer", ""),
        }
        if _is_good(row):
            sft.append(instruction)
            pairs.setdefault(row["id"], {})["chosen"] = answer["answer"]
        if _is_bad(row):
            pairs.setdefault(row["id"], {})["rejected"] = answer["answer"]
    dpo = []
    for sid, pair in pairs.items():
        sample = samples.get(sid)
        if sample and "chosen" in pair and "rejected" in pair:
            dpo.append(
                {
                    "prompt": (sample.get("payload") or {}).get("user_question", ""),
                    "chosen": pair["chosen"],
                    "rejected": pair["rejected"],
                }
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sft.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sft), encoding="utf-8")
    (out_dir / "dpo.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in dpo), encoding="utf-8")
    (out_dir / "README.md").write_text(
        "SFT/DPO 数据来自评测存档。SFT 为高分正确回答；DPO 为同题偏好对。\n"
        "训练前建议人工复核 human_review.jsonl，再过滤低质量样本。\n",
        encoding="utf-8",
    )
    result = {"sft": len(sft), "dpo": len(dpo), "out_dir": str(out_dir)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="导出微调训练数据")
    parser.add_argument("--round-dir", default=str(ROOT / "eval" / "archive" / "2026-08-15" / "round-1"))
    parser.add_argument("--out-dir", default=str(ROOT / "training"))
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES))
    args = parser.parse_args()
    export(Path(args.round_dir), Path(args.out_dir), Path(args.samples))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
