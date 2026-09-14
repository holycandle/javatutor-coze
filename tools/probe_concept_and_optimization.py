"""联调取证探针：把自定义 payload 直接打给**已部署**的智能体，取回回答与决策痕迹。

用途：联调报告的 bug 若无法在本地复现（本地没有平台模型凭据），用本脚本对线上取证。
通道复用评估系统的 remote 模式（`eval/runner/e2e_remote.chat_remote`），凭据取 `.env`：
`COZE_API_URL` / `COZE_API_TOKEN` / `COZE_PROJECT_ID`。

用法：
    uv run python tools/probe_concept_and_optimization.py --dry-run       # 只看构造出的 payload，不发请求
    uv run python tools/probe_concept_and_optimization.py                 # 跑全部用例，JSON 打到 stdout

用例（2026-09-14 联调两 bug 的现场取证）：
    concept     概念题（含 algorithm_tags / run_mode），看 intent / critic_passed / revised
    opt-step1   「帮我优化一下这段代码。」→ 期望 options 方案卡
    opt-step2   用 opt-step1 **自己返回的 options** 按前端 buildGoalPrompt 拼第二步提问
                → 期望 kind:"replace" 完整代码；线上实际返回了第二张 options 卡（Bug D）

注意：每次运行都会**真实消耗** Coze 侧的模型额度；`opt-step2` 依赖 `opt-step1` 的返回。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

DIJKSTRA = """import java.util.*;

public class Dijkstra {
    public static void main(String[] args) {
        int n = 5; // 节点数
        int[][] graph = {{0, 2, 0, 6, 0}, {2, 0, 3, 8, 5}, {0, 3, 0, 0, 7}, {6, 8, 0, 0, 9}, {0, 5, 7, 9, 0}};
        int[] dist = new int[n];
        boolean[] visited = new boolean[n];
        Arrays.fill(dist, Integer.MAX_VALUE);
        dist[0] = 0;
        System.out.println(Arrays.toString(dist));
    }
}
"""

SOLUTION = """import java.util.*;

public class Solution {
    public int[] solve(int[] nums) {
        int[] out = new int[nums.length];
        for (int i = 0; i < nums.length; i++) {
            int found = -1;
            for (int j = 0; j < nums.length; j++) {
                if (nums[j] == nums[i]) {
                    found = j;
                    break;
                }
            }
            out[i] = found;
        }
        return out;
    }
}
"""

STEPS_DIJKSTRA = [
    {"step": 1, "line": 3, "variables": {"n": 5, "args": "[]"}},
    {"step": 2, "line": 5, "variables": {"n": 5, "graph": "2D-array 5x5"}},
    {"step": 3, "line": 6, "variables": {"n": 5, "dist": "[MAX, MAX, MAX, MAX, MAX]"}},
]
STEPS_SOLUTION = [
    {"step": 1, "line": 4, "variables": {"nums": [3, 1, 3], "out": "[0, 0, 0]"}},
    {"step": 2, "line": 6, "variables": {"nums": [3, 1, 3], "i": 0, "found": 0}},
]

CONCEPT_QUESTION = "请解释「迪杰斯特拉算法」这个算法/数据结构。"
OPT_STEP1_QUESTION = "帮我优化一下这段代码。"

EDIT_MARK = "\n【编辑建议】"
GOALS = {
    "performance": "性能",
    "readability": "可读性",
    "memory": "内存",
    "style": "规范",
    "correctness": "正确性",
    "comprehensive": "综合",
}
ORDINALS = ["①", "②", "③"]


def build_goal_prompt(selected: list[dict], excluded: list[dict]) -> str:
    """与前端 `utils/editSuggestion.js::buildGoalPrompt` 同构（第二步提问模板）。"""
    if not selected:
        return ""

    def name(o: dict) -> str:
        return o.get("label") or GOALS.get(o.get("goal", ""), o.get("goal", ""))

    if len(selected) == 1:
        o = selected[0]
        head = f"只做「{name(o)}」方向的优化" + (f"，具体要求：{o['detail']}" if o.get("detail") else "")
    else:
        items = "；".join(
            f"{ORDINALS[i] if i < len(ORDINALS) else f'{i + 1}.'}「{name(o)}」"
            + (f"：{o['detail']}" if o.get("detail") else "")
            for i, o in enumerate(selected)
        )
        head = f"只做以下方向的优化：{items}"

    tail = ""
    if excluded:
        bad = "；".join(
            f"「{name(o)}」" + (f"：{o['detail']}" if o.get("detail") else "") for o in excluded
        )
        tail = f"。不要顺带做其他方向的改动（例如：{bad}）"
    return f"{head}{tail}。请给出优化后的完整代码。"


def parse_options(answer: str) -> list[dict]:
    """从回答末尾的【编辑建议】块里取 options（解析失败返回空表）。"""
    if EDIT_MARK not in (answer or ""):
        return []
    raw = answer.split(EDIT_MARK, 1)[1].strip()
    for candidate in (raw.split("\n\n")[0], raw.split("\n【决策痕迹】")[0]):
        try:
            block = json.loads(candidate.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(block, dict) and isinstance(block.get("options"), list):
            return [o for o in block["options"] if isinstance(o, dict)]
    return []


def payload(code: str, steps: list[dict], question: str, line: int, **extra) -> dict:
    body = {
        "source_code": code,
        "steps": steps,
        "current_step_index": 0,
        "current_line": line,
        "user_question": question,
        "compile_error": "",
    }
    body.update(extra)
    return body


def build_cases() -> list[dict]:
    return [
        {
            "case": "concept",
            "id": "probe-concept-dijkstra",
            "payload": payload(
                DIJKSTRA,
                STEPS_DIJKSTRA,
                CONCEPT_QUESTION,
                3,
                algorithm_tags=["迪杰斯特拉算法"],
                run_mode="default",
                test_case_count=0,
            ),
        },
        {
            "case": "opt-step1",
            "id": "probe-opt-code",
            "payload": payload(SOLUTION, STEPS_SOLUTION, OPT_STEP1_QUESTION, 6),
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="已部署智能体联调取证探针")
    parser.add_argument("--dry-run", action="store_true", help="只打印构造出的 payload，不发请求")
    parser.add_argument("--out", help="把结果写入该 JSON 文件（默认打到 stdout）")
    args = parser.parse_args()

    cases = build_cases()
    if args.dry_run:
        print(json.dumps(cases, ensure_ascii=False, indent=2))
        return 0

    load_dotenv(ROOT / ".env")
    missing = [k for k in ("COZE_API_URL", "COZE_API_TOKEN", "COZE_PROJECT_ID") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"缺少环境变量：{', '.join(missing)}（写入 {ROOT / '.env'} 后重试）")

    from eval.runner.e2e_remote import chat_remote

    url = os.environ["COZE_API_URL"]
    token = os.environ["COZE_API_TOKEN"]
    project = os.environ["COZE_PROJECT_ID"]
    results: dict = {}

    for case in cases:
        out = chat_remote(
            {"id": case["id"], "payload": case["payload"]}, url, token, project
        )
        results[case["case"]] = out
        print(f"[{case['case']}] answer_chars={len(out.get('answer') or '')}", file=sys.stderr)
        if case["case"] == "opt-step1":
            options = parse_options(out.get("answer") or "")
            question = build_goal_prompt(options[:1], options[1:])
            results["opt-step1_options"] = options
            results["opt-step2_question"] = question
            results["opt-step2"] = chat_remote(
                {
                    "id": case["id"],
                    "payload": payload(SOLUTION, STEPS_SOLUTION, question, 6),
                },
                url,
                token,
                project,
            )
            print(
                f"[opt-step2] answer_chars={len(results['opt-step2'].get('answer') or '')}",
                file=sys.stderr,
            )

    text = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"written {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
