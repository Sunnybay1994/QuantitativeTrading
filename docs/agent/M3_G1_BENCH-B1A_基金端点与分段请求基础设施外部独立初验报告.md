# M3 G1 BENCH-B1A：基金端点与分段请求基础设施外部独立初验报告

日期：2026-07-22  
角色：外部独立初验 Agent（全新会话；未参与 B1A 实现或 R1 返工）  
模型：`cursor-grok-4.5-high`  
任务书：[`M3_G1_BENCH-B1A_基金端点与分段请求基础设施任务单.md`](M3_G1_BENCH-B1A_基金端点与分段请求基础设施任务单.md)  
实现交付：[`M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部实现交付报告.md`](M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部实现交付报告.md)  
R1 任务/交付/复验：[`M3_G1_BENCH-B1A-R1_CRLF行尾污染返工任务单.md`](M3_G1_BENCH-B1A-R1_CRLF行尾污染返工任务单.md) /
[`M3_G1_BENCH-B1A-R1_CRLF行尾污染外部返工交付报告.md`](M3_G1_BENCH-B1A-R1_CRLF行尾污染外部返工交付报告.md) /
[`M3_G1_BENCH-B1A-R1_CRLF行尾污染外部独立复验报告.md`](M3_G1_BENCH-B1A-R1_CRLF行尾污染外部独立复验报告.md)  
状态：**本项独立初验通过**；**不声称 B1A / G1 / M3 Gate 或主验通过**

## 1. 范围与只读约束

- 生产代码、配置、现有测试、实现/R1 报告：只读
- 本会话唯一仓库写入：本初验报告
- 未调用真实网络 / Tushare；未读 token；未改生产或测试文件；未做 Gate 终验
- 对抗性探针仅在 `/tmp`（经 Windows Temp 映射）只读执行，不写入仓库

## 2. 逐项合同映射（独立核对，非复述交付报告）

| 冻结合同 | 初验结果 | 证据摘要 |
|---|---|---|
| fields 精确值 | 通过 | `TUSHARE_FIELDS` 三键与任务书逐字一致（含 `fund_div` 16 列） |
| policy `(5000,REJECT)/(2000,REJECT)/(5000,REJECT)` | 通过 | `ENDPOINT_POLICIES_V1`、`config.py` literal、`m3_qlib_example.toml`、`g1_planning._EMPTY_REJECT` 一致 |
| 参数键 `fund_daily/fund_adj`=`fields,ts_code,start_date,end_date`；`fund_div`=`fields,ts_code` | 通过 | `_validate_request_contract` + fake fetch 精确 kwargs 断言 |
| 六位 `.SH/.SZ`；bool/空/HK/CSI/非六位/非 date/反向日期 IO 前拒绝 | 通过 | connector + `plan_fund_adj_requests` 拒绝路径；见 §3 对抗例 |
| `plan_fund_adj_requests` 四自然年分段、连续无重叠、≤1461 | 通过 | 实现与既有 parametrize；闰日起点对抗例见 §3 |
| `_fetch` 显式三分支，无动态方法名 | 通过 | `fund_*` 为 `if spec.endpoint == ...`；`getattr(` 不在 `_fetch` 体 |
| 不建第二套 hash/journal 旁路 | 通过 | 复用既有 `_make_spec`/`request_id`/batch/验证路径 |
| 旧七 endpoint 身份与 HISTORY planner 不变 | 通过 | `plan_history_requests` 仍只发六 HISTORY 类 + 既有 identity 回归测试；无 `fund_*` |
| `g1_planning` 仅扩 policy，benchmark 仍 `H00300.CSI` | 通过 | `_BENCHMARK` 字面量；静态 plan 不发射基金请求 |
| 文件白名单 | 通过* | B1A 生产/测试改动落在任务书九文件内；*工作区另有无关脏文件，见 §4 |
| R1 后行尾 | 通过 | `test_m3_backfill_requests.py` SHA=`83713a5d...91178`；LF=2115；CRLF=0；bare CR=0；白名单八文件 + toml 均为 LF；`git diff --check` 零输出 |

## 3. 实现者未使用的对抗性反例

实现交付与既有单测覆盖了跨年/单日/恰四年/四年以上分段、非法代码、空/截断、恶意 spec、旧七 policy fail-closed 等。本初验新增（均未写入仓库测试）：

**反例 A（主）：`fund_daily` 与 `daily` 的 fields 字符串相同，但 `request_id` 必须因 endpoint 身份不同而分离。**

- 实现者交付报告仅文字提示“不得混用 request_id”，测试未断言同参跨 endpoint 哈希分离。
- 实测：`fields` 相等；`daily` rid=`056a4912da5d2bcdde46be6044dc82a15e6bfe379d25e62f3b5defae89088ada`；`fund_daily` rid=`7401657ad536ec74e3ea706dcdeb9d0e2c901fd81453f16b54107d7b0427e597`；二者不等。

**反例 B（辅）：闰日起点 `2020-02-29`→`2024-02-28`（实现者 parametrize 未含 Feb-29 起点）。**

- 分段=`[20200229–20231231, 20240101–20240228]`；首段 1402 日 ≤1461；request_id 重算稳定。

**反例 C（辅）：`datetime.datetime` 与小写/畸形后缀在任何 SDK 调用前拒绝；CountingClient.calls 保持空。**

- `datetime(2020,1,1)`、`510300.sh` / `510300.Sh` / `1510300.SH` / `510300.SHH` 均 `ValueError`。

## 4. 定向验证（WSL Miniforge `base`）

环境：`/home/mabw/AI_Coding_win/QuantitativeTrading`；`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_config.py tests/unit/test_m3_g1_planning.py -q` | **279 passed**（= 交付报告 Windows `267 passed + 12 skipped`）；exit 0 |
| `ruff check`（白名单八文件） | All checks passed；exit 0 |
| `mypy`（四生产文件） | Success: no issues found in 4 source files；exit 0 |
| `git diff --check`（白名单九路径） | 零输出；exit 0 |
| R1 SHA / 行尾复核 | 与 R1 复验报告一致 |

工作区观察（不据此否决本项）：另有 `项目实施路线图.md`、`docs/CODEX_HANDOFF.md` 等非白名单脏文件及并行文档；路线图提及 B1A 合同冻结但未勾选 Gate。本会话未修改它们。

## 5. 结论与交接

- **独立初验：通过。** 合同、白名单内实现、R1 行尾修复、定向静态/单测与新增对抗例均一致。
- **明确非声明：** 不宣布 B1A / G1 / M3 Gate 通过；不代替主 Agent 终验（含跨模块不变量、全量回归、真实依赖与文档合流）。
- 下一步：交回主 Agent 终验。
