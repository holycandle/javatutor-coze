"""JavaTutor Coze 智能体评测 CLI（本地开发工具，不属于平台外壳）。

用法：
    uv run python tools/eval_cli.py component
    uv run python tools/eval_cli.py e2e --round-dir eval/archive/2026-08-15/round-1
    uv run python tools/eval_cli.py judge --round-dir eval/archive/2026-08-15/round-1
    uv run python tools/eval_cli.py report --round-dir eval/archive/2026-08-15/round-1
    uv run python tools/eval_cli.py all --round-dir eval/archive/2026-08-15/round-1

密钥安全：
    - 从本地 .env（已 gitignore）读取 COZE_API_URL / COZE_API_TOKEN / COZE_PROJECT_ID
    - Judge 使用 JUDGE_API_URL / JUDGE_API_KEY / JUDGE_MODEL（DeepSeek）
    - 也可用 --coze-properties 指向 JavaTutor 的 coze-local.properties 作为回退
    - 本脚本不输出、不写入任何密钥
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
SAMPLES = ROOT / "eval" / "samples"
COMPONENT_CASES = SAMPLES / "component_cases.jsonl"
GOLDEN_SET = SAMPLES / "golden_set.jsonl"
DEFAULT_ROUND = ROOT / "eval" / "archive" / "2026-08-15" / "round-1"


def load_properties(path: str | Path) -> dict[str, str]:
    values = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def ensure_coze_env(args) -> None:
    if args.coze_properties:
        props = load_properties(args.coze_properties)
        mapping = {
            "coze.api.url": "COZE_API_URL",
            "coze.api.token": "COZE_API_TOKEN",
            "coze.api.project-id": "COZE_PROJECT_ID",
        }
        for props_key, env_key in mapping.items():
            os.environ.setdefault(env_key, props.get(props_key, ""))
    missing = [key for key in ("COZE_API_URL", "COZE_API_TOKEN", "COZE_PROJECT_ID") if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"缺少环境变量: {', '.join(missing)}；请在 .env 配置，或用 --coze-properties 指定属性文件")


def cmd_component(args) -> int:
    from eval.runner.component_metrics import load_jsonl, run_component_cases

    cases = load_jsonl(COMPONENT_CASES)
    metrics = run_component_cases(cases, rag_search=lambda q: [])
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def cmd_e2e(args) -> int:
    ensure_coze_env(args)
    from eval.runner.e2e_remote import run_remote_golden_set
    from eval.runner.report import load_jsonl

    samples = load_jsonl(GOLDEN_SET)
    out = args.round_dir / "answers.jsonl"
    outputs = run_remote_golden_set(
        samples,
        os.environ["COZE_API_URL"],
        os.environ["COZE_API_TOKEN"],
        os.environ["COZE_PROJECT_ID"],
        out_path=out,
    )
    print(f"answers -> {out} ({len(outputs)} 条)")
    return 0


def cmd_judge(args) -> int:
    from eval.runner.judge import judge_answer
    from eval.runner.report import load_jsonl

    samples = {s["id"]: s for s in load_jsonl(GOLDEN_SET)}
    answers = load_jsonl(args.round_dir / "answers.jsonl")
    rows = []
    for item in answers:
        sample = samples.get(item.get("id"), {})
        judged = judge_answer(sample, item.get("answer", ""))
        rows.append({**item, **judged})
    out = args.round_dir / "judged.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    print(f"judged -> {out} ({len(rows)} 条)")
    return 0


def cmd_report(args) -> int:
    from eval.runner.report import compute_extended_metrics, diff, load_jsonl, summarize, write_summary

    samples = load_jsonl(GOLDEN_SET)
    outputs = load_jsonl(args.round_dir / "answers.jsonl")
    judged = load_jsonl(args.round_dir / "judged.jsonl")
    extended = compute_extended_metrics(outputs, samples, judged)
    summary = summarize(judged, component=None, extended=extended)
    prev_dir = args.round_dir.parent / f"round-{max(1, _round_number(args.round_dir) - 1)}"
    prev_path = prev_dir / "summary.json"
    if prev_path.exists():
        previous = json.loads(prev_path.read_text(encoding="utf-8"))
        summary["diff_vs_previous"] = diff(previous, summary)
    write_summary(args.round_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_retrieval(args) -> int:
    from eval.runner.report import load_jsonl
    from eval.runner.retrieval_metrics import compute_retrieval_metrics

    samples = load_jsonl(GOLDEN_SET)
    outputs = load_jsonl(args.round_dir / "answers.jsonl")
    metrics = compute_retrieval_metrics(outputs, samples)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def cmd_winrate(args) -> int:
    from eval.runner.report import load_jsonl
    from eval.runner.winrate import compare_pair, compute_winrate

    samples = {s["id"]: s for s in load_jsonl(GOLDEN_SET)}
    answers_a = {a["id"]: a for a in load_jsonl(args.a_dir / "answers.jsonl")}
    answers_b = {a["id"]: a for a in load_jsonl(args.b_dir / "answers.jsonl")}
    comparisons = []
    for sid in sorted(set(answers_a) & set(answers_b)):
        sample = samples.get(sid, {})
        if not sample:
            continue
        comparisons.append(
            compare_pair(sample, answers_a[sid].get("answer", ""), answers_b[sid].get("answer", ""))
        )
    out = args.b_dir / "winrate.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in comparisons), encoding="utf-8")
    summary = compute_winrate(comparisons)
    summary["out"] = str(out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_review(args) -> int:
    # 注意：不能用 `tools.human_review`——src/tools（常规包，含 __init__.py）
    # 会遮蔽根目录 tools/（命名空间包），导致 ModuleNotFoundError。
    # 用脚本所在目录的直接导入即可（运行 python tools/eval_cli.py 时 sys.path[0] 即 tools/）。
    from human_review import run_review

    return run_review(args.round_dir, Path(args.samples))


def cmd_export(args) -> int:
    # 同上：避开 src/tools 遮蔽，用脚本所在目录直接导入。
    from export_training_data import export

    export(args.round_dir, Path(args.out_dir), Path(args.samples))
    return 0


def _round_number(round_dir: Path) -> int:
    try:
        return int(round_dir.name.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 1


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="JavaTutor Coze 智能体评测 CLI")
    parser.add_argument("--coze-properties", help="Java properties 文件路径（coze-local.properties），密钥不回显")
    parser.add_argument("--round-dir", default=str(DEFAULT_ROUND))
    parser.add_argument("--a-dir", default=str(DEFAULT_ROUND), help="Win Rate 旧版本 round 目录")
    parser.add_argument("--b-dir", default=str(DEFAULT_ROUND), help="Win Rate 新版本 round 目录")
    parser.add_argument("--samples", default=str(GOLDEN_SET))
    parser.add_argument("--out-dir", default=str(ROOT / "training"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("component")
    sub.add_parser("e2e")
    sub.add_parser("judge")
    sub.add_parser("report")
    sub.add_parser("retrieval")
    sub.add_parser("winrate")
    sub.add_parser("review")
    sub.add_parser("export")
    sub.add_parser("all")
    args = parser.parse_args()
    args.round_dir = Path(args.round_dir)

    if args.cmd == "component":
        return cmd_component(args)
    if args.cmd == "e2e":
        return cmd_e2e(args)
    if args.cmd == "judge":
        return cmd_judge(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "retrieval":
        return cmd_retrieval(args)
    if args.cmd == "winrate":
        return cmd_winrate(args)
    if args.cmd == "review":
        return cmd_review(args)
    if args.cmd == "export":
        return cmd_export(args)
    if args.cmd == "all":
        code = cmd_e2e(args)
        if code:
            return code
        code = cmd_judge(args)
        if code:
            return code
        return cmd_report(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
