# M3 G1 B2A 主 Agent 最终验收报告

日期：2026-07-13  
结论：**B2A 子包通过主 Agent 最终验收**  
范围：确定性 Tushare 请求计划、request raw、journal intent/candidate/receipt、逻辑响应身份、限频与分类重试

该结论只关闭 B2A 子包，不代表 B2、G1、M3 或任何 G0–G9 Gate 通过；未使用真实网络或 token。

## 1. 四段式证据链

| 阶段 | 证据 | 结论 |
|---|---|---|
| 主 Agent 任务书 | [`M3_G1_B2A请求计划与Journal实现初验任务单.md`](M3_G1_B2A请求计划与Journal实现初验任务单.md) | 冻结 B2A 边界、状态机与验收门槛 |
| 实现 Agent 首次交付 | [`M3_G1_B2A请求计划与Journal交付报告.md`](M3_G1_B2A请求计划与Journal交付报告.md) | 自测通过，但独立初验不通过 |
| 独立初验与连续复验 | [`M3_G1_B2A请求计划与Journal独立初验报告.md`](M3_G1_B2A请求计划与Journal独立初验报告.md)、[`独立复验`](M3_G1_B2A请求计划与Journal独立复验报告.md)、[`独立二次复验`](M3_G1_B2A请求计划与Journal独立二次复验报告.md)、[`独立三次复验`](M3_G1_B2A请求计划与Journal独立三次复验报告.md)、[`独立四次复验`](M3_G1_B2A请求计划与Journal独立四次复验报告.md)、[`独立五次复验`](M3_G1_B2A请求计划与Journal独立五次复验报告.md) | 逐轮发现并退回边界缺口 |
| 实现 Agent 六轮最小返工 | [`首次返工`](M3_G1_B2A请求计划与Journal返工交付报告.md)、[`二次返工`](M3_G1_B2A请求计划与Journal二次返工交付报告.md)、[`三次返工`](M3_G1_B2A请求计划与Journal三次返工交付报告.md)、[`四次返工`](M3_G1_B2A请求计划与Journal四次返工交付报告.md)、[`五次返工`](M3_G1_B2A请求计划与Journal五次返工交付报告.md)、[`六次返工`](M3_G1_B2A请求计划与Journal六次返工交付报告.md) | 原实现 Agent 按反例补生产回归和最小修复 |
| 独立六次复验 | [`M3_G1_B2A请求计划与Journal独立六次复验报告.md`](M3_G1_B2A请求计划与Journal独立六次复验报告.md) | 全部历史 P1/P2 关闭，冻结边界内无新 finding |
| 主 Agent 终验 | 本报告 | 源码、契约、工具链和文档证据复核通过 |

## 2. 主要问题与沉淀规则

独立验收没有把全量绿测当成通过证明，先后暴露了以下共同根因：

1. `Batch/Plan/Verified` 名称代表信任承诺，公开对象必须递归重算嵌套身份和内容，而不能把校验推迟到 executor。
2. 文件门禁要从 root/祖先走到本次确定 request 叶子并检查全部条目；过滤非法条目后得到空集合会误判成“尚未抓取”。
3. 零 API 不等于零副作用；失败门禁还必须比较 raw/journal 普通文件集合。
4. expected mode、candidate existence 和 raw identity 必须在首个持久化动作前比较，事后发现 closure changed 已经太晚。
5. `COMPLETE` 只是状态，不是身份；snapshot 与 frame 必须来自同一次 data/metadata bytes 读取和验真的 bundle，不能按路径二读。
6. IO 脱敏必须覆盖 publish、cleanup、Parquet 读取及 chained cause；cleanup 不得掩盖主异常。

这些规则已同步到 [`M3_G1设计审查与修订记录.md`](M3_G1设计审查与修订记录.md)，用于约束 B2B/B3/B4
和后续 artifact journal，而不是只留在历史验收报告中。

## 3. 主 Agent 源码复核

- `quant.data` → `quant.research` 反向 import：0。
- `m3_backfill.py` 中直接 `verify_request(`、`pl.read_parquet`、旧 `_read_parquet_sanitized`：均为 0；
  `verify_request_bundle` 消费点为 3。
- `RawStore.verify_request_bundle` 从同一次捕获的 data/metadata bytes 派生 checksum、size、metadata hash、
  rows、columns、frame；旧 `verify_request` 保持兼容包装。
- journal 使用原子不覆盖发布；未使用文件系统 `os.replace` 覆盖证据。
- B2A 生产与测试文件不引用 `configs/tushare.local.toml`、token 或研究层配置。
- endpoint fields、七类 policy、自然月计划、60/10 session 窗口、stable/content digest、恢复与重试均由生产测试覆盖。

## 4. 主 Agent WSL 验证

全部命令由主 Agent 在 WSL Miniforge `base` 亲自运行：

| 验证 | 结果 |
|---|---|
| B2A + storage 定向 pytest | `135 passed` |
| 全量 pytest | `436 passed, 1179 warnings` |
| Ruff `src tests` | `All checks passed!` |
| mypy `src` | `Success: no issues found in 72 source files` |

1179 条 warning 是既有 Pandera/Polars deprecation warning。WSL 的 localhost proxy 未镜像提示不影响本轮
离线命令，四个进程均 exit 0；没有把环境提示记为测试失败或代码通过证据。

## 5. 完成边界与后续

B2A 可以作为后续 G1 数据包的确定性请求与 raw journal 基础。仍未完成：真实 Tushare 小样本、G1 专用
mapper、membership/eligible keys、BaoStock 跨源对账、candidate audit、不可变 G1 release 和 B2/G1 Gate。

下一任务必须继续采用“主任务书 → 实现 Agent → 独立验收 Agent → 主 Agent 终验”。真实网络测试必须显式
标记、只读取 ignored token 配置且不输出凭据；本次验收未读取 token。
