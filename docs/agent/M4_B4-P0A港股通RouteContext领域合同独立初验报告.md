# M4 B4-P0A 港股通 RouteContext 领域合同 — 独立初验报告

日期：2026-07-17  
角色：全新外部独立初验 Agent（未参与 P0A 实现；本会话仅写本报告）  
模型：`cursor-grok-4.5-high`  
合同 SSOT：[`M4_B4-P0A港股通RouteContext领域合同任务单.md`](M4_B4-P0A港股通RouteContext领域合同任务单.md)（v2）  
对照：交付报告、独立设计审查报告、前置裁定、白名单源码与测试  
状态：**独立初验通过，可交主 Agent 终验 / 外部闭环通过待主 Agent 整体验收**  
边界：未修改生产代码/测试/配置/data；未宣称 B4/M4/Gate 完成；未跑全量 pytest / M3 workflow

工作目录：`/home/mabw/win/Cursor/quant`（WSL：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`）  
环境：`/home/mabw/miniforge3/bin/conda run -n base <command>`

## 1. 总判

逐条完成「合同—源码—测试—运行证据」映射；定向 pytest/ruff/mypy 通过；并新增实现者未使用的对抗反例全部通过。未发现 P0/P1 缺口。

**结论：独立初验通过，可交主 Agent 终验。** 本结论不等于 B4/M4/Gate 完成，也不替代主 Agent 对跨模块不变量与文档一致性的终验。

## 2. 验证命令与结果

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/unit/test_execution_contracts.py -k 'connect_market_context' tests/unit/test_execution_ports.py -k 'connect_market_context' -q` | 通过 | `9 passed, 33 deselected in 1.87s` |
| `python -m ruff check`（任务书 §5 七路径） | 通过 | `All checks passed!` |
| `python -m mypy src/quant/domain/enums.py src/quant/execution/contracts.py src/quant/execution/ports.py` | 通过 | `Success: no issues found in 3 source files` |
| 初验对抗 `python -c` / `/tmp/p0a_verify_scope.py`（只读，未改仓库测试） | 通过 | 见 §4 |
| 全量 pytest / M3 workflow | 未运行 | 任务书禁止 |

仓库无 git metadata；白名单外未改改用符号出现面 + mtime + 字段结构核对（见 §3.8）。

## 3. 合同—源码—测试—运行证据映射

### 3.1 必验-1：SH/SZ identity 不同；顺序无关稳定；固定向量命中

| 层 | 证据 |
| --- | --- |
| 合同 | 任务书 §2.2 / §4.1；冻结 hex `de53c71c…162c1` |
| 源码 | `_verified_connect_market_context_digest` 复用 `_sha256_envelope`；`type="VerifiedConnectMarketContext"`；payload 九键；`_HASH_VERSION="execution-contract-hash-v1"` |
| 测试 | `test_connect_market_context_frozen_vector_and_route_identity` |
| 运行 | 定向 pytest 通过；初验独立重算 envelope → 精确命中同一 hex |

### 3.2 必验-2：route / bool / as_of / date 类型失败

| 层 | 证据 |
| --- | --- |
| 合同 | 精确 `ConnectRoute`；精确 `bool`；UTC aware `as_of`；严格 `date` |
| 源码 | `_require_enum` / `_require_bool`（`type is bool`）/ `_require_utc_datetime` / `_require_date`（拒 datetime） |
| 测试 | `test_connect_market_context_rejects_route_bool_and_time_types`：裸 string、`AUTO`、`Market.SH`、伪 Enum、三 bool 的 0/1、naive/non-UTC、date↔datetime 混用 |
| 运行 | 定向 pytest 通过 |

### 3.3 必验-3：上游三 identity 格式与 forged context_id

| 层 | 证据 |
| --- | --- |
| 合同 | 64 位小写 hex；forged / 同 id 异 payload 失败 |
| 源码 | `_require_hex64`；`__post_init__` + `_reject_forged_identity` |
| 测试 | `test_connect_market_context_rejects_upstream_id_and_forged_context_id`：大写、63/65、非 hex；伪造 `0*64`；SH 的 id 配 SZ payload |
| 运行 | 定向 pytest 通过 |

### 3.4 必验-4：`object.__setattr__` 篡改后 identity 拒绝

| 层 | 证据 |
| --- | --- |
| 合同 | 篡改任一经济字段后 identity builder 拒绝 |
| 源码 | `build_verified_connect_market_context_identity` 从当前字段重算并 `_reject_forged_identity` |
| 测试 | `test_connect_market_context_setattr_tamper_rejects_identity`（九经济字段） |
| 运行 | 定向 pytest 通过 |

### 3.5 必验-5：Protocol good/缺方法；runtime_checkable ≠ 返回闭包

| 层 | 证据 |
| --- | --- |
| 合同 | good fake 通过；缺方法不通过；错误签名/错误 route/未来 as_of/错误返回类型证明闭包非 Protocol 职责 |
| 源码 | `@runtime_checkable ConnectMarketContextRepository`；docstring 明示 adapter/caller 须再验闭包 |
| 测试 | `test_connect_market_context_protocol_runtime_checkable`、`test_connect_market_context_runtime_checkable_not_return_closure` |
| 运行 | 定向 pytest 通过；初验 ADV9 补充「错误 session_date 仍 isinstance」 |

### 3.6 必验-6：import 隔离

| 层 | 证据 |
| --- | --- |
| 合同 | domain/contracts/ports 不 import `quant.data` / `quant.backtest` / 研究框架 / 网络 SDK |
| 源码 | 三文件 import 闭包仅 domain enums + 标准库 + 本包 contracts |
| 测试 | `test_connect_market_context_import_isolation`、`test_connect_market_context_port_import_isolation` |
| 运行 | 定向 pytest 通过；初验源码扫描无禁依赖 token |

### 3.7 必验-7：双开市可分裂构造；provenance / 微秒敏感；伪 Enum

| 层 | 证据 |
| --- | --- |
| 合同 | mainland=True、hong_kong_open=False、quota=True 可构造；改 quota_identity / as_of 微秒 → id 变；伪 Enum 拒 |
| 源码 | 无 `connect_open` 约束；九字段全部进入 digest |
| 测试 | `test_connect_market_context_bool_split_and_provenance_sensitivity` + FakeRoute 用例 |
| 运行 | 定向 pytest 通过；初验 ADV2/3/5/8 补充 calendar/source 敏感与对称分裂 |

### 3.8 必验-8：白名单外未改

| 检查 | 证据 |
| --- | --- |
| 符号出现面 | `ConnectRoute` / `VerifiedConnectMarketContext` / `ConnectMarketContextRepository` 仅出现于白名单生产五文件 + 两 unit tests + 相关 docs；`src/` 无其它消费 |
| OrderIntent / SymbolMarketState | 无 `connect_route` / 无 route 字段；遗留 `buy_quota_available` 仍在 SymbolMarketState |
| B2 | `connect_execution.py` 仍用 `_CONNECT_ROUTES` 字符串集，未 import `ConnectRoute`；mtime `01:25` 早于 P0A 源码 `12:24+` |
| TradingConfig | `config.py` 无 ConnectRoute 引用；mtime `10:29` 早于 P0A |
| schemas / portfolio / data | schemas mtime Jul 14；portfolio Jul 12；P0A 符号未渗入 |
| P0B 边界 | 未实现 Intent/Snapshot/B2 接入（符合 P0A 留白） |

## 4. 实现者未用的对抗反例（初验新增）

以下均以一次性只读 `python -c` / `/tmp` 脚本执行，**未修改仓库测试文件**。结果：`ALL_ADVERSARIAL_PASSED` / `ALL_SCOPE_CHECKS_OK`。

| ID | 反例（实现者未覆盖或仅侧面覆盖） | 结果 |
| --- | --- | --- |
| ADV1 | 独立调用 `_sha256_envelope` 重算固定向量 | 命中 `de53c71c…162c1` |
| ADV2 | 仅改 `calendar_identity`（实现者只测了 quota_identity） | context_id 变化 |
| ADV3 | 仅改 `source_identity` | context_id 变化 |
| ADV4 | builder 位置参数调用 | `TypeError`（keyword-only） |
| ADV5 | mainland=False、hong_kong_open=True、quota=False 可构造 | 成功且 id≠冻结向量 |
| ADV6 | 别名 kwargs：`mainland_market` / `connect_open` / `hk_open` | 均 `TypeError` |
| ADV7 | identity builder 接受 `SimpleNamespace` | `TypeError` |
| ADV8 | 同 `calendar_identity`、不同开市 bool 均可构造（不透明 provenance） | 成功且 id 不同 |
| ADV9 | Protocol fake 返回错误 `session_date` 仍 `isinstance` | True（闭包非 Protocol） |
| ADV10 | 非精确 bool 的 truthy `int` 子类 | `ContractError` |

## 5. 与交付报告的核对

| 交付声明 | 初验裁定 |
| --- | --- |
| 固定向量命中 | 确认（测试 + 独立 envelope） |
| 9 项定向测试 / ruff / mypy | 复跑通过（9 passed） |
| 未改 B2/P3/Config/Intent/repository/data | 符号面 + 字段 + mtime 支持；无 git 故不能给 commit-level 证明 |
| 未宣称 Gate | 交付报告表述合规；本初验亦不宣称 |

未发现交付报告夸大或与源码矛盾之处。已知限制与合同一致：`runtime_checkable` 不构成返回闭包，须由 adapter/P0B 调用侧 fail closed。

## 6. 缺陷清单

无 P0 / P1。无返工项。

## 7. 裁定

**独立初验通过，可交主 Agent 终验 / 外部闭环通过待主 Agent 整体验收。**

固定向量：

```text
context_id=de53c71c001da5fa70feb5cc5f2745431d9c9107350e0903052a8bd527e162c1
```

关键缺口：无（P0A 范围内）。P0B 迁移、真实 repository adapter、B4 planner 均不在本初验范围。

本报告唯一写入路径：`docs/agent/M4_B4-P0A港股通RouteContext领域合同独立初验报告.md`。
