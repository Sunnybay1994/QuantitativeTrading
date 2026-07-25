# 2026-07-24 Windows 原生接任交接：任务书与启动 Prompt

> 交接点：上一外部 Cursor 协调会话 → **同一 Windows 工作区** 新会话接任继续跑。  
> 环境已是 Windows（`F:\…` + `D:\Miniforge3\python.exe`），**不是**「再切到 Windows」。WSL2 本阶段仍先不管。  
> **不宣称** G1 Gate / Codex 终验 / 正式 HISTORY workflow 通过。未进入 REFERENCE/PREPARE/PUBLISH。

## 1. 接任角色与环境

你是 QuantitativeTrading 的外部 Cursor **协调 Agent**，在**当前已打开的 Windows 工作区**接任，按 `AGENTS.md` 四段式职责分离推进。

| 项 | 值 |
|---|---|
| 工作区（已在用） | `F:\AI_Coding\QuantitativeTrading` |
| WSL 同目录（本阶段**先不用**） | `/home/mabw/AI_Coding_win/QuantitativeTrading` |
| Python | `D:\Miniforge3\python.exe` |
| 配置 | `configs/research/m3_qlib_example.toml` |
| Git HEAD（接任时） | `ed77978`（**脏工作树，禁止 reset/checkout/批量换行**） |
| 用户约束 | 继续 Windows 原生推进；暂不考虑 WSL2；full candidate 前阻碍自行解 |

## 2. 接任前必读（按序）

1. `AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`
2. 本文件 + [`20260723_Windows原生推进进度_协调续作.md`](20260723_Windows原生推进进度_协调续作.md)
3. 较早总报告（背景，部分阻塞已 superseded）：[`20260723_外部Cursor协调Agent阶段性最终交付总报告.md`](20260723_外部Cursor协调Agent阶段性最终交付总报告.md)
4. 合同修订（本轮解阻权威）：
   - [`M3_G1_窗内缺ex_date实施行审计省略合同修订.md`](M3_G1_窗内缺ex_date实施行审计省略合同修订.md)（含零经济效果省略；旧 `002131` 裁定已 superseded）
   - [`M3_G1_stk_limit缺pre_close用daily补全合同修订.md`](M3_G1_stk_limit缺pre_close用daily补全合同修订.md)
   - [`M3_G1_窗内首个factor日公司行动对账省略合同修订.md`](M3_G1_窗内首个factor日公司行动对账省略合同修订.md)
   - [`M3_G1_无dividend事件因子跳变接受合同修订.md`](M3_G1_无dividend事件因子跳变接受合同修订.md)
5. 诊断证据：`artifacts/g1_component_diag_20260722/summary.json`

先只读：`git status --short`、定向 diff。保护全部未提交改动。

## 3. 已完成（勿重复宣称 Gate）

### 3.1 零网络分层诊断（Windows，权威）

| 项 | 值 |
|---|---|
| 状态 | **ALL_LAYERS_PASSED** |
| `primary_candidate_key` 前缀 | `9e4013366068443c` |
| bars / factors / benchmark | 1489629 / 1517796 / 2614 |
| 网络 / 写正式数据 | false / false |
| 脚本 | `artifacts/g1_component_diag_20260722/diagnose_component_invalid.py` |

已越过：`corporate_action_selection` → `price_limit_coverage` → `corporate_action_reconciliation` → `_build_candidate_body`。

这是 **INSPECT/零网络组件诊断**，**不是** 正式 G1 workflow HISTORY stage 绿灯，也不是 Codex 终验。

### 3.2 代码与合同（本轮生产增量，相对 `ed77978`）

主要文件：

- `src/quant/data/m3_execution_facts.py`（选版省略；limit daily 补全；coverage 无 bar 豁免；对账边界/回退）
- `src/quant/data/m3_g1_candidate.py` / `m3_release.py` / `__init__.py`（传入 `daily_pre_close` 与 `bars`）
- `tests/unit/test_m3_execution_facts.py`（定向 **57 passed**）
- 另有脏树中更早的 BENCH/R5 等改动，一并保护

### 3.3 解阻要点（勿回退）

| 问题 | 处置 |
|---|---|
| `002131.SZ` 实施行窗内 `ex_date=null` | 合同：实施 + null ex_date → 省略；零经济效果 → 省略 |
| `stk_limit.pre_close` null/0 但有上下限 | 同日 `daily.pre_close` 落入区间则发出 clean 行 |
| coverage 日历开市但无同日 bar | 不进 required（同 FULL_DAY） |
| 首个 factor 日 / 无 prior bar 事件 | 不对账匹配 |
| 因子未跳变却有 dividend | 按无事件 |
| 无事件因子跳变（如配股 `000661`） | 接受 `NO_EVENT_STABLE_FACTOR` |
| 有事件但公式无法闭合 | 回退无事件，不再 `UNEXPLAINED` fail-closed |
| 方法版本字符串 | **不 bump** `tushare_stk_limit_suspension_aware_v1`（避免冻结 plan 身份漂移） |

### 3.4 探针与禁止

- `002131` dividend 旁路探针已做过：`vendor_ex_date_fixed=false`；正式 identity **不可覆盖重写**。
- **禁止** 再拉五个 `510300.SH` 正式 API；零网络优先；不输出 token。
- Windows 绿测 **不能** 写成 Linux Gate / PUBLISH 通过。

## 4. 当前真实下一步（Windows）

优先级从高到低：

1. **确认脏树与定向回归**  
   `D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py -q`  
   可选：`test_m3_g1_candidate.py` / `test_m3_reference.py` 中与 price_limit / reconcile 相关项。

2. **正式 G1 workflow 在 Windows 上推进到 candidate / HISTORY stage**（零网络 resume）  
   - 配置仍用 `m3_qlib_example.toml`；复用已有 raw/receipt/journal。  
   - 长命令：持久日志 + rc；已知 full candidate 级任务可达 **数十分钟～数小时**，禁止分钟级空轮询。  
   - 若仍 `G1_CANDIDATE_*` / quality 失败：继续零网络分层定位，自行解阻；高风险合同变更先写修订文档。  
   - **通过标准**：正式 stage 状态机绿灯 + 可复现日志；仍 **不** 自动宣称 Codex 终验。

3. **职责分离**  
   高风险实现 / 独立初验仍宜分会话（`cursor-grok-4.5-high`）；用户已授权协调者在 Windows 上直接解阻时，可直改但必须同步合同文档与测试。

4. **仍勿进入**  
   REFERENCE / PREPARE / PUBLISH（PUBLISH 需经探针的 WSL2 ext4；用户说先不管 WSL2）。

## 5. 诊断复跑（可选）

```powershell
cd F:\AI_Coding\QuantitativeTrading
# 不要用 shell 重定向抢 stdout；脚本自写 diag.log / summary.json
D:\Miniforge3\python.exe artifacts\g1_component_diag_20260722\diagnose_component_invalid.py
# 预期：summary.json status=ALL_LAYERS_PASSED，key 前缀与上次一致或按身份规则可解释
```

中间若只到 `RECON_PASSED`，说明对账已过、正在跑完整 `_build_candidate_body`（很重，可能再需 ~30min+）。

## 6. CLI 教训

Windows `cursor-agent` ArgumentList 中文易截断：用短 ASCII boot 指向 UTF-8 prompt 文件（可把下文 §7 存成 `docs/agent/_boot_win_handoff_prompt.txt`）。

## 7. 可直接复制的启动 Prompt

```text
你是 QuantitativeTrading 外部 Cursor 协调 Agent，在 Windows 原生环境继续推进 M3 G1。

工作区：F:\AI_Coding\QuantitativeTrading
Python：D:\Miniforge3\python.exe
配置：configs/research/m3_qlib_example.toml
Git HEAD 接任时：ed77978（脏工作树必须全程保护：禁止 reset/checkout/批量换行）

必读：
1) AGENTS.md、.ai/README.md、.ai/coding_rules.md
2) docs/agent/20260724_Windows原生接任交接_任务书与启动Prompt.md
3) docs/agent/20260723_Windows原生推进进度_协调续作.md
4) 四份合同修订：窗内缺ex_date省略；stk_limit缺pre_close用daily补全；窗内首个factor日对账省略；无dividend事件因子跳变接受
5) artifacts/g1_component_diag_20260722/summary.json（应为 ALL_LAYERS_PASSED，key 前缀 9e4013366068443c）

用户约束（有效）：
- 先保 Windows 原生；暂不考虑 WSL2 / PUBLISH
- full candidate 通过前的阻碍自行解决；高风险合同变更先写 docs/agent 修订
- 零网络优先；禁止重复五个 510300.SH 正式 API；不输出 token
- Windows 绿测不能写成 Linux Gate；不宣称 Codex 终验 / VerifiedG1Release，除非证据齐全

已完成（勿重做诊断宣称）：
- 零网络分层诊断 ALL_LAYERS_PASSED：corporate_action_selection → price_limit_coverage → reconciliation → _build_candidate_body
- 002131 等公司行动省略合同、limit daily 补全、coverage 无 bar 豁免、对账边界/回退已落地
- tests/unit/test_m3_execution_facts.py 定向 57 passed

你的第一优先级：
1) git status + 定向 pytest 确认环境
2) 在 Windows 上用正式 G1 workflow 零网络 resume 推进 candidate/HISTORY stage；长命令持久日志+rc，禁止分钟级空轮询
3) 若失败：零网络分层定位并自行解阻；同步合同/测试/进度文档
4) 未进入 REFERENCE/PREPARE/PUBLISH；不重拉 510300 五身份

用中文简体汇报。每步写清：做了什么、证据路径、是否仍失败、下一步唯一动作。
```

## 8. 给用户的粘贴方式

1. 新开 Cursor Agent 会话（工作区指向 `F:\AI_Coding\QuantitativeTrading`）。  
2. 把 §7 整段粘贴为第一条用户消息（或先存 UTF-8 文件再 `@` 引用本交接文档）。  
3. 确认本机 `D:\Miniforge3\python.exe` 可用后再让 Agent 开跑。
