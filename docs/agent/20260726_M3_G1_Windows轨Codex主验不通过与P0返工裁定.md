# 2026-07-26 M3 G1 Windows 轨：Codex 主验不通过与 P0 返工裁定

## 1. 结论

**本轮不通过 Codex 最终验收。** Windows 原生 `PUBLISH` 的技术产物已经落盘并能进入
`verify_g1_release`，但该 release 建立在两项会把数据缺陷误判为绿色的合同回退之上，且若干高风险修改缺少
“外部实现 → 另一全新外部独立初验”的仓库证据。因此 release
`3c9bda840ada5f81d202036ba812971b3e6d54f9950f50a783cdad961b584d10` 只保留为本轮 Windows 诊断产物，
不得作为 G2A 输入或表述为 G1 Gate 通过。

本裁定不否认以下已证明事实：INDEX、HISTORY、REFERENCE、PREPARE 和 Windows PUBLISH 命令均实际走到
`SUCCESS`；也不宣称 Linux/ext4 Gate。

## 2. 已确认的正向证据

- Git 检查点存在：`f7322d0`、`41c8e3f`、`68ea536`、`7b7a38e`、`68cd40e`。
- `formal_reference_win_v3.out.log`：REFERENCE SUCCESS，key=`cc50d836...`，30 个 BaoStock 请求。
- `formal_prepare_win_v3.out.log`：PREPARE SUCCESS，release_id=`3c9bda84...`。
- `formal_publish_win_v3.out.log`：PUBLISH SUCCESS，manifest SHA-256=`a09f0f11...`。
- release 目录含 16 个受控文件；`quality.json` 为 `passed=true/error_count=0/warning_count=0`。
- Codex Windows 定向回归：
  - `test_m3_execution_facts.py`：57 passed；
  - candidate 关键两项：2 passed；
  - Windows publish/verify 关键五项：5 passed；
  - 定向 Ruff：通过；定向 mypy：3 个源文件 0 issues；`git diff --check`：通过。
- Codex 从磁盘调用 `verify_g1_release` 已成功返回对象；第一次打印脚本随后错误读取了不存在的
  `VerifiedG1Release.primary_candidate_key` 便捷属性，该打印错误不发生在 verifier 内部。

## 3. 阻断项

### P0-1：公司行动 reconciliation 违反已冻结 fail-closed 合同

权威任务书 `M3_G1_P3_B2C执行事实外部闭环任务单.md` §9.2 冻结：无事件 transition 只有
`abs(actual-1)<=rtol` 才能输出 `NO_EVENT_STABLE_FACTOR`；无事件 jump、缺前收、event 证明路径均超容差等
必须 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。

当前实现却在无事件时无条件写 `NO_EVENT_STABLE_FACTOR`，并把 event 分支的多种证明失败也回退成无事件。
当前测试甚至明确接受 `actual_factor_ratio=1.5`。这使名称为“STABLE”的行可保存任意跳变，导致
reconciliation 不再证明 adjustment factor 与公司行动事实闭合。

影响：正式 release 的 `quality.passed=true` 不能证明原 B2C/P4A 合同，G1 不得关闭。

### P0-2：candidate audit 允许只剩 1 个 eligible 成员

当前 audit 把每个 signal session 的成员数条件放宽为 `[1,300]`。Codex 使用现有测试 helper 将合法 candidate
的 `eligible_keys` 重绑定为单行，结果为：

```text
eligible_rows=1, audit_passed=True, issue_codes=[]
```

这会让大规模 membership/eligible 丢失在自洽重算 digest 后通过。299 的真实退市生命周期现象应由
`index_membership.build_observed_membership` 从 observations、calendar、instrument 精确重建证明，而不是把
下界放宽到 1。

### P1-1：方法版本未随语义变化

`stk_limit` null `pre_close` 的 daily 补全、公司行动 null `ex_date` 省略及 reconciliation 失败语义均发生实质
变化，但 `G1_PRICE_LIMIT_METHOD_VERSION`、`G1_CORPORATE_ACTION_SELECTION_VERSION`、
`G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 仍沿用已验收 v1 字符串。`build_code_version` 的源码树哈希不能
替代业务算法版本；必须逐项审计并为仍保留的新语义升级版本。

### P1-2：高风险职责分离证据不闭合

ledger event-id、空腿和较早的窗外 ex-date 修复已有任务/实现/独立初验报告；但后续“窗内 null ex-date 一律
省略”、价限 daily 补全、reconciliation 广泛回退、membership audit 放宽及 Windows PUBLISH 实现，在当前
仓库中只有协调修订/诊断文档，缺少对应的外部实现交付和另一全新会话独立初验闭包。不可变发布、交易语义和
身份均属于 `AGENTS.md` 明定高风险范围。

### P1-3：项目状态文档仍是旧事实

`docs/CODEX_HANDOFF.md`、`docs/M3当前验收与返工总览.md` 和 `项目实施路线图.md` 仍写“candidate 失败、没有
VerifiedG1Release”。返工完成前应保留“Windows 诊断 release 已生成但主验不通过”的准确边界；新 release
通过后再统一同步，不能直接把 G1/M3 勾为完成。

## 4. 返工通过条件

1. 恢复/重建 B2C fail-closed 语义；未知资本事件不得伪装成 `NO_EVENT_STABLE_FACTOR`。
2. candidate audit 从现有 observations/calendar/instrument 精确重建 membership 与 eligible keys 并逐表比较；
   单成员自洽篡改必须失败，真实 299 仅在权威 builder 精确产生时通过。
3. 审计所有发生语义变化的方法版本并按实际合同升级；不得为避免 key 漂移保留错误版本。
4. 由全新外部实现 Agent 返工，再由另一全新外部 Agent 增加未公开反例并独立初验；Windows PUBLISH 也需独立
   审核 no-clobber、二进制完整性、reparse/symlink 和声明边界。
5. 源码修订必然改变 build code identity；旧 release 不得复用。先零网络复用 3190 HISTORY receipts，再按新
   key 运行必要的 REFERENCE、PREPARE、Windows PUBLISH，并从磁盘重新 `verify_g1_release`。
6. 全程禁止重复五个 510300 正式 API identity；新 reference 若因新 key 改变抽样，按 journal 合同有界执行。
7. 新 release 与外部初验闭合后，才交回 Codex 再次最终验收；此前不启动真实 G2A。

