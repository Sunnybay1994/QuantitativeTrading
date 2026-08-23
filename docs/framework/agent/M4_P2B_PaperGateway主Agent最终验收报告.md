# M4-P2B PaperGateway 主 Agent 最终验收报告

日期：2026-08-11  
结论：**PASS；关闭 P2B PaperGateway 工程合同，允许后续 formal 装配消费；不关闭 P2 整包、M4、WSL2/ext4 或真实 PAPER Gate。**

## 1. 验收范围

- 冻结合约：[`M4_P2B_PaperGateway任务单.md`](M4_P2B_PaperGateway任务单.md)
- 实现交付：[`M4_P2B_PaperGateway实现报告.md`](M4_P2B_PaperGateway实现报告.md)
- 外部独立初验：[`M4_P2B_PaperGateway外部独立初验报告.md`](M4_P2B_PaperGateway外部独立初验报告.md)
- 生产：`src/quant/execution/gateways/paper.py`
- 邻接：gateway contracts、OMS、cost/FX；未连接真实 broker、网络、SQLite 或 formal runner。

## 2. 主验裁决

主 Agent 逐项核对冻结合同、实现和独立初验报告，并确认：

1. PAPER submit/replay/restart 的 callback identity、attempt/session/broker/time fencing 与 P2A 结果边界一致。
2. `NOT_SENT`/`UNKNOWN` 不产生经济 callback；UNKNOWN 不被自动重发。
3. policy rejection code 是闭合集合；未知或 hostile 返回统一 fail closed，输入和内部异常图不回显。
4. cancel→late partial→cancelled 与 cancel→full fill 只接受 shared OMS 可达序列；同 event id 同 payload 幂等，同 id 异 payload 拒绝。
5. 模块保持确定性、无 IO；cold import 不加载 SQLite、网络或研究重依赖。

外部独立初验补充了实现者未使用的 unknown policy code、同 id 异载荷、cancel/fill race、attempt/session/timezone、subclass/duck 与递归异常图对抗，Windows 和 WSL/DrvFS 同组均为 **133 passed**，Ruff/mypy 通过。该 WSL 结果只算 DrvFS 开发兼容，不是 ext4 Gate。

## 3. 主 Agent 独立验证

Windows `D:\Miniforge3\python.exe`，显式 `PYTHONPATH=src`：

- 8 个高风险指定节点（含参数化）终态：**14 passed**；
- Ruff：`paper.py` + `test_paper_gateway.py`，PASS；
- mypy：`paper.py`，PASS；
- fresh cold import：PASS，未加载 `sqlite3/requests/qlib/lightgbm/mlflow`；
- scoped `git diff --check`：PASS。

主验没有重复外部初验刚完成的双平台 133 项全组，遵循项目定向验证优先规则。

## 4. 保留边界与后续

- P2B 是 development PAPER adapter 工程合同，不签发 formal runtime/account/store capability。
- RUN-0B2D formal account、formal store/gateway factory、ServiceFactory、schedule/runner 和真实 28 日 soak 仍未实现或未完成。
- 当前 WSL1/DrvFS 不能关闭 Linux `RENAME_NOREPLACE`/ext4 Gate。
- 本工作树仍有大量未跟踪/未提交文件；本报告不等于主树已合流。

最终裁决：**M4-P2B PASS，可作为后续 formal gateway 装配的已验收前置；不扩大为 P2/M4 Gate。**

