# 2026-08-09 — SVG 动画生成器

## 背景
用户要求为排序、搜索、DP、树、图、链表等算法生成 SVG 动画，用于可视化代码执行过程。

## 完成内容

### 4.1 基础架构
- `src/learning/animation.py`：`build_animation_svg()` 主入口 + 7 个渲染函数
- 7 个 SVG 模板（Jinja2）：`sort_bars`、`search_bars`、`dp_table`、`tree_traversal`、`graph_path`、`linked_list`
- 算法分类器 `classify_algorithm()`：正则匹配 6 类 + other

### 4.2 算法标签优先机制
- 新增 `_map_tags_to_category()`：从 analyze 节点返回的 `algorithm_tags` 映射动画类别
- `animate_node` 优先使用标签，无法映射时回退 `classify_algorithm`
- 解决用户将冒泡排序类名写成 `UserCode` 时被错误识别为 `other` 的问题

### 4.3 自适应数据发现
- `_find_array_var()`：自动检测 steps 中变化最大的数组变量
- `_series_from_steps()`：自适应变量名（arr/nums/list/dp...）
- `_render_dp()`：支持一维 DP 表格 + 二维 DP 矩阵双模式，解决 int[] dp 被当作 "无 DP 数据" 的问题

### 4.4 排序动画交换 Bug 修复
- 根因：柱子绑定位置下标而非值身份，交换时 from_x 始终指向初始位置
- 修复：值身份追踪，`cur_pos` 维护每个值的实时位置，from_x 取上一轮 to_x
- 柱顶数值 `<text>` 跟随柱子移动

### 4.5 模板增强
- 所有模板新增：`variable_name`（变量名）、`step_count`（步数）、柱顶/格内数值标注
- 数据不足时友好提示，替代 "暂无XX数据"

## 测试
- 30+ 个动画测试，涵盖 7 类算法、自适应发现、一维 DP、值身份追踪
- 全部通过

## 关键文件
- `src/learning/animation.py`
- `assets/svg_templates/sort_bars.svg.j2`
- `assets/svg_templates/search_bars.svg.j2`
- `assets/svg_templates/dp_table.svg.j2`
- `assets/svg_templates/tree_traversal.svg.j2`
- `assets/svg_templates/graph_path.svg.j2`
- `assets/svg_templates/linked_list.svg.j2`