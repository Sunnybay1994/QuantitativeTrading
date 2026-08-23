# M3 G7C R2 replay/transition 来源与全局排序返工交付报告

日期：2026-08-09  
角色：R2 返工实现 Agent  
结论：**R2 白名单返工与双平台组合自测完成；等待全新独立复验，不宣称主验或 M3 Gate 通过**

## 1. R1 三项失败闭环

### 1.1 transition 完整输出来源

- `AShareEntitlementReplayTransition` 已从普通 dataclass 改为一次性 closure 产生的 exact runtime type；公开
  constructor、`dataclasses.replace`、`object.__new__`、slots clone 均不能产生可消费对象。
- transition attestation 绑定 input-state attestation、operation、date、facts identity、canonical quantity mapping
  输入、输出 replay、完整有序 postings、cash delta、settled stock、nonce 与 exact instance identity。
- 每个 property 和 `repr` 返回前都复验 issued registry、输出内容和 HMAC；真实 transition 删除全部/单条 posting、
  修改顺序/delta/stock、跨 operation 复用或字段漂移均失效。纯 expected helper 不接触签发闭包。

### 1.2 state 来源闭包

- `AShareEntitlementReplayState` 同样改为 closure exact runtime type；state attestation 绑定 facts identity、index、
  phase、全部 positions、processed IDs、record quantities、nonce 与 exact instance identity。
- public initialize/advance/capture 是唯一 state/transition 签发路径；初始化 closure 在模块装载后删除。R1 的模块级
  registry、fingerprint、generic register/issue helper 已全部移除。
- public callable graph 只保留 exact instance verify/consume 与三条完整业务入口，不存在接受裸 payload 后登记的
  register/sign/mint/factory callable。即使通过 closure introspection 向 WeakSet 加入 slots clone，exact-instance
  attestation 仍拒绝该 clone。

### 1.3 跨日 event ID 全局排序

- 每日事件仍先按 G7D-F0 已验物理事实和当天 event ID 处理；新 record evidence 与历史 evidence 合并后再按
  event ID 做全局 canonical 存储。
- processed IDs、record quantities 和 positions 的全局顺序不再隐含 record-date 单调性。早日 `b...`、晚日
  `a...` 的合法 replay 可继续推进，最终证据为 `a..., b...`。
- 日期可达性仍由 ledger record/ex/due、当前 execution index 和 phase 独立复算，未用全局排序代替时间语义。

## 2. Reload 与兼容性

- formal state/transition 每次 reload 都产生新的 exact runtime type；旧对象在 fresh subprocess 中被新模块拒绝。
- development `EntitlementPosition`、`EntitlementPosting`、`EntitlementTransition`、稳定错误和 phase enum 在 reload
  时保留身份，避免已有 `ledger.py`、simulator 等邻接模块持有旧 development 类型后出现 exact-type 污染。
- fixed-order `development reload -> M4 ledger` 精确回归已通过；reload 测试留在 fresh subprocess，不污染主测试进程。
- RIGHTs、日期、Decimal、cash/stock 经济语义和 development primitive 行为未改变。

## 3. 文件范围

- `src/quant/backtest/corporate_actions.py`
- `src/quant/backtest/__init__.py`（R1 已有安全导出，无新增旁路）
- `tests/unit/test_m3_formal_corporate_actions.py`
- `docs/framework/agent/M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md`（R2 状态与主 Agent §12 重冻）
- 本报告

未修改 R1 交付报告、R1 独立初验报告、G7D-F0/G7E/G1、配置、domain schema/enum 或正式 artifact/journal；
未联网、未 add/commit。

## 4. 新增对抗性覆盖

- public constructor、replace、new、slots clone、字段漂移、registry+clone 组合旁路；
- CAPTURE/ADVANCE transition 删除完整 posting tuple、clone/重签、exact-instance 漂移；
- module/public callable graph 无 raw issuer；initializer 装载后删除；
- 跨 record day event ID 逆序、同日 event ID 顺序、所有 recognize 先于所有 settle；
- fixed-order formal reload，旧 state/transition 拒绝，新 state 正常，development primitive 正常；
- R1 已有 facts identity、RIGHTS、HALF_UP、hostile context、quantity/position 双向复算和完整 release replay继续通过。

## 5. 验证证据

所有命令均显式使用本 worktree `src`。

Windows `D:\Miniforge3\python.exe`：

- R2 formal 首轮：`6 passed, 1 failed`；唯一失败是测试误用空-posting PRE_OPEN transition，改为真实 CAPTURE
  transition 后精确节点 `1 passed`；
- Windows 组合回归首次：`72 passed, 1 failed`；唯一失败为既有 main-process development reload 改变 dataclass
  身份、随后 M4 ledger exact-type 不匹配；实现 reload 身份保持后精确 fixed-order 两节点 `2 passed`；
- 受该修正直接影响的 formal reload + public graph 两节点：`2 passed`；
- 最终 Ruff：PASS；最终 mypy：`Success: no issues found in 1 source file`；cold import/surface 探针：PASS。

为遵守任务书“不重复长测”，未机械重跑已完成的整套 Windows 73 节点；所有首次失败均已用其精确最小节点
复核，且相同最终代码随后在 WSL 组合套件取得完整绿色。

WSL Miniforge base，绝对 worktree `PYTHONPATH`：

- R2 formal + development + G7D-F0 + G7E development + M4 ledger 组合：`73 passed`；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；cold import/surface 探针：PASS。

最终 scoped `git diff --check` 与 Ruff 均 PASS。当前 WSL 路径为 `/mnt/f` DrvFS，不是 ext4；上述只算双平台
工程兼容证据，不等于 Linux/ext4、真实 full-work、完整账户回测或 M3 Gate 关闭。

## 6. 后续

必须由未参与 R1/R2 实现的全新独立上下文执行 R2 复验。建议至少攻击：transition 删除单个 mixed posting 后
尝试 whole-field clone、直接 closure registry 写入配合 exact slots clone、窗前/窗内 event ID 交错、reload 后旧
package export 与新 module type 混配，以及同日多 event recognize/settle 交错重排。
