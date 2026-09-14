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
    opt-step2   用 opt-step1 **自己返回的 options** 拼第二步提问（**带 `【优化第二步】` 标记**）
                → 期望 kind:"replace" 完整代码；修复前线上返回了第二张 options 卡（Bug D）

**第二步提问必须带标记**：2026-09-14 起「是否第二步」的唯一判别器是提问起头的
`【优化第二步】`（coze `prompting/optimization.py::STEP2_MARKER`，由前端 `buildGoalPrompt` 写出）。
本脚本的 `build_goal_prompt` 直接 import 该常量，**不再自己复制一份字面量**——此前它漏了标记，
于是「第二步提问」变成了没有标记的第一步，任何用它复跑的人都会看到 options 卡而误判为修复无效。

诊断字段：`diagnosis` 会据「第二步返回的块 kind」×「决策痕迹三键是否在位」区分三类结论——
未重发 / 判别器未生效 / coze 侧已修好（问题在前端或部署侧）。

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
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from graphs.javatutor.prompting.optimization import STEP2_MARKER  # noqa: E402

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
TRACE_MARK = "\n【决策痕迹】"
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
    """与前端 `utils/editSuggestion.js::buildGoalPrompt` 同构（第二步提问模板）。

    起头必须是 `STEP2_MARKER`：那是 coze 侧判别「第二步」的**唯一**依据，
    缺了它这提问就变成没有标记的第一步（agent 只会再给一张方案卡）。
    """
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
    return f"{STEP2_MARKER}{head}{tail}。请给出优化后的完整代码。"


def _json_after(text: str, mark: str) -> dict:
    """取 `mark` 之后的第一段 JSON 对象（解析失败返回空 dict）。"""
    if mark not in (text or ""):
        return {}
    raw = text.split(mark, 1)[1].lstrip()
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def plan_kind(answer: str) -> str:
    """回答里【编辑建议】块的 kind：options / replace / patch（无块返回空串）。

    `edits` 数组无 `kind` 键 ⇒ 记 `patch`（与前端 `normalizePlan` 的缺省一致）。
    """
    obj = _json_after(answer or "", EDIT_MARK)
    if not obj:
        return ""
    if "kind" in obj:
        return str(obj["kind"])
    return "patch" if isinstance(obj.get("edits"), list) else ""


def trace_of(answer: str) -> dict:
    """取回答尾部【决策痕迹】JSON（取不到返回空 dict）。"""
    return _json_after(answer or "", TRACE_MARK)


# 2026-09-14 批次（评审优化计划 Task 6）落在决策痕迹里的三个新键。
# 在位 ⇒ 已部署构建含该批次（本次 Bug D 修法就在同一批），不在位 ⇒ 几乎只能是没有重发。
BATCH_TRACE_KEYS = ("critic_issues", "revise_outcome", "revise_revert_reason")


def diagnose(step2_answer: str, traces: list[dict]) -> dict:
    """据「第二步返回的块 kind」×「痕迹三键是否在位」给出结论（不猜、只判可观测事实）。"""
    kind = plan_kind(step2_answer or "")
    present = sorted(k for k in BATCH_TRACE_KEYS if any(k in t for t in traces if t))
    batch_deployed = bool(present)

    if not step2_answer:
        verdict = "no-answer"
    elif kind == "replace":
        verdict = "coze-side-ok"
        detail = "第二步返回了 replace：coze 侧判别器生效 ⇒ 问题在前端是否发标记或部署是否同步"
    elif kind == "options" and not batch_deployed:
        verdict = "not-redeployed"
        detail = "第二步仍给 options 且痕迹缺批次三键 ⇒ 已部署构建早于本次修复，先重发再验"
    elif kind == "options":
        verdict = "discriminator-ineffective"
        detail = "第二步仍给 options 但批次痕迹在位 ⇒ 提示词判别器未生效，需查提问是否真的以标记起头"
    else:
        verdict = "other-kind"
        detail = f"第二步返回的块 kind = {kind!r}（既非 options 也非 replace）"
    return {
        "step2_plan_kind": kind,
        "batch_trace_keys_present": present,
        "batch_deployed": batch_deployed,
        "verdict": verdict,
        "detail": detail,
    }


def parse_options(answer: str) -> list[dict]:
    """从回答末尾的【编辑建议】块里取 options（解析失败返回空表）。

    必须用 `JSONDecoder().raw_decode` 平衡解析：早先按 `"\\n\\n"` 切分的写法，遇到
    「options 块后面紧跟【视角导航】块」（真实产出就是这样）两个候选串都会解析失败，
    于是**静默**回落到 fixture，`--out` 产物里看不出「第二步用的是模型自己给的选项
    还是固定样本」（2026-09-14 实测踩到）。
    """
    block = _json_after(answer or "", EDIT_MARK)
    opts = block.get("options") if isinstance(block, dict) else None
    return [o for o in opts if isinstance(o, dict)] if isinstance(opts, list) else []


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
            # 第一步没给出可解析的 options 时用固定 fixture，否则第二步整段跑不起来
            # （这一步只验「带标记的提问会不会拿到 replace」，不依赖选项是不是模型自己产出的）。
            source = "step1" if options else "fixture"
            if not options:
                options = [
                    {"goal": "performance", "label": "以性能为先", "detail": "用哈希表把嵌套循环降为 O(n)"},
                    {"goal": "readability", "label": "以可读性为先", "detail": "拆分长方法并命名中间变量"},
                ]
            question = build_goal_prompt(options[:1], options[1:])
            assert question.startswith(STEP2_MARKER), "第二步提问必须以标记起头（判别器唯一依据）"
            results["opt-step1_options"] = options
            results["opt-step2_options_source"] = source
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
                f"[opt-step2] answer_chars={len(results['opt-step2'].get('answer') or '')} "
                f"kind={plan_kind(results['opt-step2'].get('answer') or '') or '(none)'}",
                file=sys.stderr,
            )

    # 诊断（只读上面的回答，不发请求）：结论随产物一起落盘，避免「复跑一次各说各话」
    traces = [trace_of(v.get("answer") or "") for v in results.values() if isinstance(v, dict)]
    results["diagnosis"] = diagnose((results.get("opt-step2") or {}).get("answer") or "", traces)
    results["traces"] = traces
    print(
        f"[diagnosis] {results['diagnosis']['verdict']} — {results['diagnosis']['detail']}",
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
