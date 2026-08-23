# M3 G1 R1B / R1C-A 主 Agent 最终验收报告

日期：2026-07-17  
角色：主 Agent 最终验收  
结论：**R1B 与 R1C-A 子包最终验收通过**；**不代表 R1C-B、R1C、G1 或 M3 Gate 通过**。

## 1. 验收范围

本次仅验收以下轻量闭环：

- R1B：可恢复 G1 workflow 服务骨架；
- R1C-A：fake / 零网络的分阶段 CLI；
- 主验返工 F1–F4：workflow state 自证、CLI result 自证、项目内 config 路径闭包、argparse 失败后的 command 归属。

R1C-B 真实全量 PREPARE、正式 PUBLISH、`VerifiedG1Release` 和 G1 Gate 均不在本次范围。

## 2. 外部职责分离证据

- 实现与返工：[`M3_G1_R1B_R1C-A主验返工交付报告.md`](M3_G1_R1B_R1C-A主验返工交付报告.md)
- 全新外部独立初验：[`M3_G1_R1B_R1C-A主验返工独立初验报告.md`](M3_G1_R1B_R1C-A主验返工独立初验报告.md)
- 原主验问题与冻结合同：[`M3_G1_R1B_R1C-A主Agent终验报告.md`](M3_G1_R1B_R1C-A主Agent终验报告.md)、[`M3_G1_R1B_R1C-A主验返工任务单.md`](M3_G1_R1B_R1C-A主验返工任务单.md)

外部独立初验逐项确认 F1–F4，并增加 8 个实现者未使用的组合反例；全部被拒绝且错误信息脱敏。初验还在 30 秒硬超时下复现两项防挂测试，结果为 `2 passed`。

## 3. 主 Agent 独立验证

### 3.1 定向回归

此前已独立执行：

```text
tests/unit/test_m3_run_g1.py tests/unit/test_m3_g1_workflow.py
-k "not five_stage_fake"
→ 53 passed, 1 deselected in 19s
```

本轮再次以 Linux 硬超时执行两项防挂测试：

```text
timeout -s KILL 30 python -m pytest \
  tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_bidirectional_closure \
  tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_does_not_hang -q --tb=line
→ 2 passed in 5.27s；timeout 未触发
```

未执行全量 pytest，也未重跑已知构造量过大的 `five_stage_fake`；当前验证已覆盖本次改动和返工合同，符合开发阶段效率原则。

### 3.2 静态与残留检查

- 仓库内无 `_diag*.py` 临时诊断文件；
- 两个目标生产文件未使用 `os.replace`；
- `--token` 只存在于 CLI 禁用参数和拒绝逻辑中，本次未读取 token、未联网；
- 外部初验报告记录定向 Ruff 与 mypy 均通过；
- 未发现越出返工白名单的生产代码修改。

## 4. 契约结论

- `VerifiedG1WorkflowStateV1` 对阶段、产物、response 顺序和 verified plan totals 做双向自证；
- `G1CliResultV1` 对小写裸 64 hex、identity 生命周期和 error 字段闭包做构造期自证；
- config 仅接受项目根内相对路径，拒绝 `..`、末端/祖先 symlink，并以读取前后 fingerprint 检测 TOCTOU；
- argparse 后续失败仍保留无歧义识别出的 command，参数值形似子命令时不会误归属；
- 上述失败均走稳定、脱敏的值错误或 CLI 错误合同。

## 5. 已知限制与下一步

1. R1C-B 需要真实数据和额度授权；在授权前不得启动真实全量 PREPARE。
2. 正式 PUBLISH 仍要求目标 release root 具备原子 `RENAME_NOREPLACE`，且必须产出正式 `VerifiedG1Release`；fake release 不得替代。
3. 完整五阶段大 fixture 的性能问题属于测试构造成本，不是 journal 死锁；后续应先缩小 fixture 或在关键 Gate 阶段单独运行，不能把它放回普通定向回归。
4. 本报告只关闭 R1B 与 R1C-A 子包主验，不勾选 G1/M3 Gate。

