"""人工复核 CLI：逐条审阅回答与 Judge 结果，输出 human_review.jsonl。

用法：
    uv run python tools/human_review.py --round-dir eval/archive/2026-08-15/round-1

判定：approve / reject / revision；备注可选；输入 quit 提前结束。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "eval" / "samples" / "golden_set.jsonl"


def load_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _format_judge(j: dict) -> str:
    """把 judged 记录格式化成可读的评分摘要，不 dump 整条 JSON。"""
    if not j:
        return "（无 Judge 结果）"
    if j.get("judge_fallback"):
        if j.get("empty_output"):
            return f"⚠ 未能评分（DeepSeek 空返回，attempts={j.get('attempts')}）"
        if j.get("error"):
            return f"⚠ 未能评分（调用异常: {j.get('error')}）"
        raw = (j.get("raw_judge_output") or "").strip()
        snippet = raw[:120] if raw else "（空）"
        return f"⚠ 未能评分（解析失败，attempts={j.get('attempts')}）raw: {snippet}"
    scores = j.get("scores") or {}
    dims = "  ".join(f"{k}={v}" for k, v in scores.items())
    return (
        f"score={j.get('score')}  judgement={j.get('judgement')}\n"
        f"  维度: {dims}\n"
        f"  理由: {j.get('reason', '')}"
    )


def run_review(round_dir: Path, samples_path: Path) -> int:
    samples = {s["id"]: s for s in load_jsonl(samples_path)}
    answers = load_jsonl(round_dir / "answers.jsonl")
    judged = {j["id"]: j for j in load_jsonl(round_dir / "judged.jsonl")}
    reviews = []
    for item in answers:
        sample = samples.get(item.get("id"), {})
        question = (sample.get("payload") or {}).get("user_question", "")
        print("=" * 60)
        print(f"[{item.get('id')}] 问题: {question}")
        print()
        print("───── 回答 ─────")
        print(item.get("answer", ""))
        print()
        print("───── Judge 评分 ─────")
        print(_format_judge(judged.get(item.get("id"), {})))
        verdict = input("审核 (approve/reject/revision, 输入 quit 结束) [approve]: ").strip() or "approve"
        if verdict == "quit":
            break
        reason = input("备注 (可选): ").strip()
        reviews.append({"id": item.get("id"), "verdict": verdict, "reason": reason})
    out = round_dir / "human_review.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in reviews), encoding="utf-8")
    print(f"human_review -> {out} ({len(reviews)} 条)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="人工复核评测结果")
    parser.add_argument("--round-dir", default=str(ROOT / "eval" / "archive" / "2026-08-15" / "round-1"))
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES))
    args = parser.parse_args()
    return run_review(Path(args.round_dir), Path(args.samples))


if __name__ == "__main__":
    raise SystemExit(main())
