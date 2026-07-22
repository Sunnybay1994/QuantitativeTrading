# M4 B4-P0A 港股通 RouteContext 领域合同 — 交付报告

日期：2026-07-17  
角色：外部实现 Agent（`cursor-grok-4.5-high`）  
合同：[`M4_B4-P0A港股通RouteContext领域合同任务单.md`](M4_B4-P0A港股通RouteContext领域合同任务单.md)（v2）  
状态：**已交付，待独立初验**（不宣称 B4 / M4 / Gate 完成）

## 结果

- 状态：已交付
- 实现了 `ConnectRoute`、`VerifiedConnectMarketContext`、两个 build API、窄
  `ConnectMarketContextRepository` Protocol，以及 domain/execution 包根导出。
- 复用 D0 `_sha256_envelope`（`execution-contract-hash-v1` / `type=VerifiedConnectMarketContext`）；
  固定向量命中冻结 hex `de53c71c…162c1`。
- 明确未修改：B2、P3、TradingConfig、OrderIntent、SymbolMarketState、repository 实现、
  数据、历史报告、路线图；未初始化 Git；未跑全量 pytest；未宣称 Gate/M4/B4 完成。

## 修改文件及目的

| 文件 | 目的 |
| --- | --- |
| `src/quant/domain/enums.py` | 新增 `ConnectRoute` SSOT |
| `src/quant/domain/__init__.py` | 包根导出 `ConnectRoute` |
| `src/quant/execution/contracts.py` | `VerifiedConnectMarketContext` + digest/build/identity |
| `src/quant/execution/ports.py` | 窄 `ConnectMarketContextRepository` Protocol |
| `src/quant/execution/__init__.py` | 导出 context/build/Protocol |
| `tests/unit/test_execution_contracts.py` | `-k connect_market_context` 合同反例 |
| `tests/unit/test_execution_ports.py` | Protocol runtime_checkable / 非闭包证明 |
| `docs/agent/M4_B4-P0A港股通RouteContext领域合同交付报告.md` | 本报告 |

## 设计与合同证据

| 成功标准 | 实现 / 测试证据 |
| --- | --- |
| `ConnectRoute` 仅 SH/SZ，新代码不复制字符串集合 | enums + 包导出；测试拒裸 string/`AUTO`/伪 Enum |
| 九字段 keyword-only builder；拒自报 `context_id`/别名 | builder 签名；`TypeError` 覆盖 `context_id`/`hk_open` |
| 精确 bool、UTC `as_of`、严格 `date` | `_require_*`；0/1、naive/non-UTC、date/datetime 混用反例 |
| 上游三 identity 为不透明 64 小写 hex | 格式校验纳入 identity；不 import backtest/data |
| 复用 `_sha256_envelope`；固定向量命中 | 锁定 hex 断言 + 顺序无关重建稳定 |
| SH/SZ identity 不同；quota_identity / as_of 微秒敏感 | 对应断言通过 |
| mainland=True、HK=False、quota=True 可构造 | 无 `connect_open` 约束 |
| setattr 篡改后 identity 拒绝 | 九经济字段逐一 `__setattr__` |
| Protocol good/缺方法；runtime_checkable ≠ 返回闭包 | ports 测试：错误 route/未来 as_of/错误返回类型仍可 isinstance |
| import 隔离 | 扫描 enums/contracts/ports 源码禁 quant.data/backtest/SDK |

关键假设确认：固定向量按任务书 payload 用既有 envelope 算法可复现；代码事实未推翻 v2。
与计划无偏离。

## 验证

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/unit/test_execution_contracts.py -k 'connect_market_context' tests/unit/test_execution_ports.py -k 'connect_market_context' -q` | 通过 | `9 passed, 33 deselected in 1.81s`（wall ~9.05s） |
| `python -m ruff check`（任务书白名单 7 路径） | 通过 | `All checks passed!`（~10.21s） |
| `python -m mypy src/quant/domain/enums.py src/quant/execution/contracts.py src/quant/execution/ports.py` | 通过 | `Success: no issues found in 3 source files`（~11.19s） |
| 包根导出烟雾（ConnectRoute / build / 固定 hex） | 通过 | `exports_ok` |
| 全量 pytest / M3 workflow | 未运行 | 任务书禁止 |

环境：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

## 清理与范围审查

- 无临时代码、无第二套 JSON/hash helper、无 repository 实现、无 P0B 迁移。
- 范围外改动：无。
- 文档：仅本交付报告；未改路线图/历史报告。

## 风险与交接

- 已知限制：`runtime_checkable` 不证明返回闭包；adapter/P0B 调用侧须再验
  route/session_date 全等与 `context.as_of <=` 查询 `as_of`。
- 未验证：独立初验对抗例、真实数据/网络、B2/P3/Intent 接入（属 P0B）。
- 下一步：未参与实现的外部初验 Agent 只读核对；主 Agent 终验前不得宣称 B4/M4 Gate。
