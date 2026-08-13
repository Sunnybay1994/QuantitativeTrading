# M3 G8D-F1 R2：FINISHED 远端 Run 全标签复用闭包主 Agent 最终验收报告

日期：2026-08-10

结论：**PASS**。G8D-F1 formal Tracking StageRunner 单 WORK wave 的工程合同已闭合，可进入下一 G8 增量设计。该结论不代表真实 MLflow、Linux ext4、完整 G8、M3 或任何实盘 Gate 通过。

## 1. 验收链

- R1 外部实现与自测完成后，由未参与实现的外部 Cursor 独立初验；初验发现 FINISHED run 仅比较五个 protected tags，`formal_gate_eligible` 漂移仍可复用，结论 FAIL。
- 主 Agent 复核任务单 §5/§6 与实现，确认问题成立，并在任务单 §13 冻结最小返工：request tags 与 protected tags 全部逐键逐值一致才可复用，额外普通远端标签仍允许。
- 全新外部 Cursor 完成 R2 最小返工；另一全新外部 Cursor 使用不同错误值、缺失组合、hostile Mapping、非 FINISHED、多匹配与 protected 漂移独立复验，结论 PASS。
- 主 Agent 未直接修改生产/测试，独立执行阻断节点、静态、冷导入、SHA、diff 与合同审查。

## 2. 最终合同结论

- formal request 仍为 exact 34 inputs、11 uploads、22 params、2 request tags；远端 create 首写 request tags 与五个 protected identity tags。
- 仅一个 `FINISHED` run 且七个期望键逐键逐值一致时可复用；任一 request/protected tag 缺失或漂移、非 FINISHED、多匹配均 fail-closed，且不创建第二 run。
- 远端额外普通标签不参与 exact-set 比较，不破坏外部系统附加元数据。
- request → remote → marker、外置 lock、首次/resume/`resume=False`/orphan、fresh exact-once、稳定异常脱敏和 development API 均保持 R1 合同。
- WSL1/DrvFS 的 `RENAME_NOREPLACE` 能力为 false，仅允许冻结的 actual publish 窄 skip；没有非原子 fallback。

## 3. 动态证据

外部 R2 实现：Windows G8D unit 9 passed、golden 2 passed、journal+G8R1 邻接 14 passed；WSL base 23 passed/1 skipped；双平台 Ruff/mypy/cold 通过。

外部独立复验：上述双平台组再次通过；独立对抗使用 `TRUE`、`1`、前导空格、`Formal`、空值、分别缺失/双缺等实现者未用组合，全部冲突路径 `create_calls==0`；七键一致并带额外普通标签复用同一 run id；hostile Mapping 与递归异常图稳定脱敏。

主 Agent 最小复验：

- Windows 阻断节点：1 passed，190.25s；
- WSL base/DrvFS 同节点：1 passed，150.59s；
- Windows/WSL 定向 Ruff：PASS；
- Windows/WSL 定向 mypy：PASS；
- Windows/WSL 冷导入：PASS，未加载 MLflow/Qlib/LightGBM；
- scoped `git diff --check`：PASS。

主验首次两次冷导入批次仅因 PowerShell 内嵌 Python 引号解析失败，未执行产品代码、不计证据；改用单引号完整程序与直接 WSL Python 调用后双平台明确 PASS。

## 4. 冻结 SHA256

- `tracking.py`: `b7b63fafd90baeb2d689e499ea86ff9e212c374bef4d76994336131b44e5ad91`
- `tracking_stage.py`: `cf4ae7a8fea7b9c0ffefb8e0ec0732d9394448d95f95804512a3be7236160063`
- `quant.research.m3.__init__`: `866b5a1f7abe4d90d37f6106cf6756a16ed0d38b173118f5e6e8a54bb5c86e11`
- G8D-F1 unit: `849d9151fdc56371ca58af5767ea209fdf29716f7cef3b48b88435ef605f5846`
- G8D-F1 golden: `f83e82d747a69c187c5b3521fc657b9ff19323c9b9b69e964ba25b4e610af903`

## 5. 残余边界

- 未运行真实 MLflow、网络、正式 G1 artifact 或正式 tracking target。
- 当前 WSL 是 WSL1/DrvFS，不是 Linux ext4；actual atomic publication Gate 仍开放。
- G8C CLI、G8E/G8F、真实 handlers 与更高层 Gate 仍须按职责分离继续实施和验收。
- 工作树保留既有未提交变更；本轮未 `git add`、commit 或写正式 artifact。

因此只允许声明：**G8D-F1 formal Tracking StageRunner 工程合同主验 PASS**。
