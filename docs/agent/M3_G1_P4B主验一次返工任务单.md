# M3 G1-P4B：主验一次返工任务单

日期：2026-07-15  
状态：独立复验通过后，主 Agent 最终验收发现 P1 身份闭包缺口；返回原实现 Agent 返工  
原任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)  
前次返工：[`M3_G1_P4B独立初验返工任务单.md`](M3_G1_P4B独立初验返工任务单.md)  
独立复验：[`M3_G1_P4B独立初验一次返工独立复验报告.md`](M3_G1_P4B独立初验一次返工独立复验报告.md)

## 1. 判定与范围

以下不是不影响主流程的展示/诊断小问题，而是 P4C 将持久化和重建的 reconciliation 证据仍有多种“自洽但非
canonical”的表示，破坏一请求一响应和 detail 语义唯一性。因此 P4B 主验暂不通过。

只允许修改：

- `src/quant/data/m3_reference.py` 中 `_derive_cross_source_from_detail` / bundle 的直接闭包；
- `tests/unit/test_m3_reference.py`；
- 新增 `docs/M3_G1_P4B主验一次返工交付报告.md`。

不得修改公共接口、connector、P4A、RawStore、其他测试、配置、路线图或历史报告。

## 2. H1：缺失行 detail 仍可携带任意 tolerance

### 现象

真实 `missing_side="REFERENCE"` 的五格 detail 把 `tolerance` 从生产生成的 `0.0` 全部改为 `123.0`，再重算
detail/summary hash，bundle 构造成功。

### 根因

shared helper 对缺失行只要求 tolerance 为 finite/nonnegative，没有要求生产 canonical 值 `0.0`。

### 应遵循规则

原任务书 §7.6/§7.8 和前次返工 F1 要求 detail 的 null/tolerance/matched 语义可由 bundle 从 policy 重建；现行
`reconcile_cross_source` 对任一缺侧固定输出 `abs_diff=None`、`relative_diff=None`、`tolerance=0.0`、
`matched=False`。同一语义不能允许无限多个 hash 不同的表示。

### 最小复现

主 Agent 临时测试 `test_main_hidden_missing_rows_require_fixed_zero_tolerance`：构造一条缺 reference 的真实 bundle，
仅把该 key 五格 tolerance 改为 `123.0` 并重绑两个 hash；期望 `ValueError`，实际未抛。临时测试已删除。

### 新增测试 / 通过条件

PRIMARY、REFERENCE、BOTH 三类缺失行的 tolerance 只接受 exact float `0.0`；`-0.0` 可按 Python 数值相等语义视为
0，不引入 bytes 级额外规则。任意其他 finite 值、NaN/Inf、null、错误 dtype 必拒；正常缺行/停牌继续通过。

## 3. H2：缺失行的现存侧数值未做领域校验

### 现象

同一真实缺 reference bundle 中，把现存 primary 的五个值改为 `-1.0` 并重绑 hash，bundle 构造成功。

### 根因

helper 的 PRIMARY/REFERENCE 分支只验证哪一侧为 null，没有验证另一侧的 float/finite/价格正值/成交量非负合同。

### 应遵循规则

detail 是标准 clean 主源与已验证 reference 的证据投影：任一存在侧必须为 exact finite float；
`open/high/low/close > 0.0`，`volume >= 0.0`。这与 `reconcile_cross_source` 的输入验证一致，且是 bundle 可从自身
字段验证的 canonical 语义。

### 最小复现

主 Agent 临时测试 `test_main_hidden_missing_rows_validate_the_present_side_domain_value`：缺 reference 时把现存 primary
值改为 `-1.0`，重绑 hash；期望 `ValueError`，实际未抛。临时测试已删除。

### 新增测试 / 通过条件

分别覆盖 PRIMARY/REFERENCE 的价格 `0/-1/NaN/Inf` 和 volume `-1/NaN/Inf` 必拒；价格正值、volume=0 合法；
BOTH 必须两侧均 null。底层 Polars/数学异常统一稳定 `ValueError`，不得含 raw 值。

## 4. H3：30 requests 可只对应 29 个唯一 stable response digests

### 现象

保留 30 个唯一 request_id，把第二个 receipt 的 `stable_response_sha256` 改成第一个的 digest，同时把
`summary.reference_receipt_digests` 和 summary hash 自洽改成 29 个唯一 digest，bundle 构造成功。

### 根因

构造器要求 30 个 receipt 和 request_id 唯一，却只比较 `sorted(set(stable_response_sha256))`，没有要求该集合也
精确 30 个。前次独立反例只保留原 30-digest summary，未覆盖“两边一起自洽重绑”。

### 应遵循规则

stable response hash envelope 含 request_id；P4B 固定 30 个不同 request。除密码学碰撞外，每个 request 必须对应
一个不同 stable response identity。发布合同必须 fail closed，不能把两个 request 压成同一响应身份。

### 最小复现

主 Agent 临时测试
`test_main_hidden_reference_stable_response_digests_remain_one_per_request`：同时重绑 receipt 与 summary unique 集合；
期望 `ValueError`，实际未抛。临时测试已删除。

### 新增测试 / 通过条件

bundle 必须要求 30 个 receipt 的 `stable_response_sha256` 也精确唯一，且 summary digest tuple 长度为 30 并与之
完全相等。新增“仅 receipt 漂移”“仅 summary 漂移”“二者自洽同漂移”三类测试；均必拒，正常 30 对 30 通过。

## 5. 交付与复验

实现者先新增 H1–H3 回归，再做最小修复；依次运行返工定向、P4B+connector、P4A、全量 pytest、Ruff、mypy。
生成 `docs/M3_G1_P4B主验一次返工交付报告.md`，逐项保留“现象—根因—规则—最小复现—新增测试—通过条件”，
状态仅“待独立复验/待主验”。

随后由全新外部会话重放上述三个主验反例，并至少增加两个未使用变体，尤其覆盖缺 PRIMARY 与 30 digest 同漂移。
复验通过后才返回主 Agent 再终验。`missing_primary` planner 可达性和 raw symlink 错误码仍只记为非阻塞观察，本轮
不扩大修复。不得声明 B4/G1/M3/Gate 通过。
