"""评审 × Judge 交叉表审计（**只读归档，不发任何请求、不消耗模型额度**）。

设计依据：`docs/spec/2026-09-14-critic-revise-optimization-design.md` §1.2 / CD-6。
用途：把「评审是否鸡肋」从争论变成任何人有可复跑的数字。

用法：

```bash
uv run python tools/critic_audit.py eval/archive                  # 全部轮次汇总
uv run python tools/critic_audit.py eval/archive/2026-09-13       # 单轮
uv run python tools/critic_audit.py eval/archive --json           # 机器可读（供比对）
```

期望（2026-09-14 的四轮归档）：`评审判失败 33 / 触发修订 27`、`precision 22/33`、`recall 10/22`，
按意图 `debug 14(5) / data_query 13(3) / other 5(2) / concept 1(1)`。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from runner.critic_agreement import (  # noqa: E402
    aggregate_critic_agreement,
    format_audit_table,
    load_judged,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评审 × Judge 交叉表（只读归档）")
    parser.add_argument(
        "paths", nargs="*", default=["eval/archive"],
        help="归档目录（含 judged.jsonl）或单文件；缺省 eval/archive",
    )
    parser.add_argument("--json", action="store_true", help="输出聚合 JSON（机器可读）")
    args = parser.parse_args(argv)

    records = load_judged(args.paths or ["eval/archive"])
    agg = aggregate_critic_agreement(records)

    if args.json:
        print(json.dumps(agg, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print(format_audit_table(agg))
    # 没有样本不算失败（可能只是还没归档），但要让调用方能区分「空」与「有数」。
    return 0 if agg["n"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
