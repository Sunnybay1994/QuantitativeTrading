# M4 P8 RUN-0B2E R2：Formal Policy 来源与 Reload 隔离返工报告

日期：2026-08-12  
角色：主 Agent（按用户最新协作指示直接串行返工与验证）  
状态：**返工完成；Windows 工程合同绿色**

## 1. 现象与根因

R1 审查发现两个需要关闭的问题：

1. `PaperBrokerPolicyDescriptor` 的 formal classification 只靠公开字段和 digest 复算，caller 可把 development descriptor `replace` 为 formal 并同步重算 digest，绕过 formal builder 的 exact policy/binding 来源要求。
2. binding/account 的 reload 对抗测试在父 pytest 进程中直接 `importlib.reload`，导致后续已收集模块保留旧 exact class identity，完整邻接出现与业务无关的顺序污染。

## 2. 最小修正

- formal descriptor 改为 slots/weak-reference 值对象；唯一 formal builder 将本次签发的 exact 实例登记到 builder/prover 共享的 closure-private identity weak-reference registry，模块不暴露可写 registry。
- B1 `_prove_policy` 对 formal classification 除字段/digest 复算外，还要求 registry 中存在同一 exact 对象；development builder 与既有 identity 保持不变。
- 增加 development descriptor 手工 `replace` + whole-rehash 反例，必须稳定拒绝。
- 增加 B1 rollback 遇到未知并发文件时保留现场的回归。
- binding/account reload 对抗改在 fresh pytest 子进程运行；父进程不再污染下游 exact type，reload 后旧 capability 失效的原始断言不变。

该来源证明是 process-local 工程边界，不宣称抵抗任意 Python 内存篡改或非 callable 反射攻击。

主 Agent 串行收尾时另补 same-value `dataclasses.replace` clone 反例，证明 provenance 判定按对象身份而不是 dataclass equality；当前 B1 + formal focused 为 `19 passed`，定向 Ruff/mypy 绿色。该检查属于正常开发验证，不另设或宣称内部独立初验。

## 3. 验证

```text
fixed order: binding reload -> account -> formal store
3 passed in 14.23s

runtime + policy + binding + account + B1 store + formal store
124 passed, 37 skipped in 49.50s

Ruff
All checks passed!

mypy
Success: no issues found in 3 source files
```

Windows skips 是既有平台特有用例；本报告不把 Windows 结果表述为 Linux/ext4 Gate。

## 4. 变更范围

- `src/quant/execution/paper_broker_store.py`
- `tests/unit/test_paper_formal_broker_store.py`
- `tests/unit/test_paper_broker_binding.py`
- `tests/unit/test_paper_account.py`
- 本任务状态与本报告

未修改 runtime/F0、policy、binding/account 生产合同、gateway/service/CLI/soak、config 或正式运行目录。
