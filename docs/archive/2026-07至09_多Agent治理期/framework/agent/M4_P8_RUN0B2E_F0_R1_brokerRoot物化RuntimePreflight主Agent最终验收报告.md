# M4 P8 RUN-0B2E-F0 R1：broker root 物化态 Runtime Preflight 主 Agent 最终验收报告

日期：2026-08-12  
角色：主 Agent 最终契约验收  
结论：**PASS；允许进入 B2E formal store opener；不宣称正式运行或 ext4 Gate 通过**

## 1. 验收范围

主验核对了冻结任务书、Cursor `auto` 实现交付报告、另一全新 Cursor `auto` 独立复验报告、生产实现与正式测试。实现者与独立复验者职责分离成立。主验未修改生产代码、测试、配置或任何 runtime/broker root。

## 2. 契约结论

1. public API 与参数未改变；caller 无法传入 mode、path、identity 或 `allow_materialized`。
2. exact formal config 只接受互斥两态：五根均 absent 的 cold，或仅 `broker_root` 为真实非 link/reparse 目录的 broker-materialized；development 仍严格要求五根 absent。
3. materialized identity 使用 `materialized-paper-runtime-root-v1`，绑定 role、parent identity、canonical path、device、inode 与 directory mode；cold 与 materialized 的 layout/verification identity 必异。
4. cold capability 在 broker root 物化后 fail closed；materialized root、parent 或同路径目录实体替换均因 fresh identity 不同而拒绝。
5. broker 内部文件树明确不进入 runtime identity；这是后续 store opener 的职责边界，不是缺口。
6. 实现只读探测文件系统；未创建 root、未打开 SQLite、未访问 network/socket/log；错误保持脱敏且 cause/context 为 `None`。

## 3. 验证证据

外部独立初验在 Windows 得到：runtime `30 passed, 35 skipped`，policy+binding `40 passed, 1 skipped`，account `37 passed, 1 skipped`；Ruff、mypy、cold import、scoped diff-check 均通过，并补充 15/15 个 retained-layout、junction、replacement、hostile 零写对抗。

主验在最终 revision 追加窄验证：

```text
broker materialized / internal tree / development isolation /
non-broker roots / junction / hostile zero-write: 9 passed
Ruff: All checks passed
mypy: Success: no issues found in 1 source file
cold import: RUN0B2EF0_MAIN_COLD_PASS
```

Windows formal fresh mint 全链仍受 RUN-0A 平台约束而跳过；当前用户指示暂不以 Linux/ext4 为前置，因此该边界不阻断本工程合同，但不得据此宣称正式 Gate。

## 4. 裁决

**PASS。** RUN-0B2E-F0 已关闭“broker root 一旦物化便无法重新 fresh runtime 链”的架构缺口。后续 B2E store opener 必须消费 cold capability 创建唯一 broker root，再重新签发 broker-materialized runtime/policy/binding/account 链，并由 store 层验证内部 tree；不得复用已失效的 cold capability。
