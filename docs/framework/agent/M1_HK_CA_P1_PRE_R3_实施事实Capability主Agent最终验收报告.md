# M1-HK-CA-P1-PRE R3：实施事实 Capability 主 Agent 最终验收报告

日期：2026-08-09  
结论：**实施事实来源无关开发合同 PASS；HK bar capability 仍 blocked**

## 1. 验收范围

本次只验收 P1-PRE 中“P0 canonical actions → source-verified implemented set”的来源无关工程合同。HK bar
availability、receipt v3、真实 HK 公司行动来源、01065/HK60、复权公式、WSL2/ext4 与 M1 Gate 不在通过范围。

主验复核了冻结任务书及R1-R3闭环、R3实现/测试、实现交付报告和全新独立复验报告；没有把实现者自测或
development fixture表述为真实来源验收。

## 2. 主验结论

- retained adapter必须从canonical implementation records解析明确状态/确认时间/撤回记录，P0只做exact
  event/revision/source对账；只有scope flag或P0 ACTIVE不能推导IMPLEMENTED。
- capability在builder、source wrapper、selector和public set verifier复用同一fresh exact-type preflight；普通
  子类/多层继承、source/version漂移均fail closed。
- source wrapper签发的projection attestation绑定P0 result、implementation raw bundle、candidate/evidence与
  source/version；合法另一闭包whole-rehash不能复用旧token。
- withdrawal parser先验证全部future/known records的strict text、UTC observation因果、P0 link、source/business
  uniqueness与canonical order，再应用query as-of；不会被早期known withdrawal短路后续非法scope检查。
- exact-content capability copy保持相同语义可消费；projection/verified set仍不可pickle，module reload后的旧
  capability/projection fail closed。没有错误地引入instance-unique身份。
- hostile adapter与P0 verifier统一稳定错误，cause/context为空，traceback不暴露marker。

独立复验补充的两层继承、known-first + later invalid future、合法raw/P0/version whole-rehash旧token、hostile
异常与exact event set均通过，因此R3已关闭R1/R2阻断。

## 3. 主 Agent 验证

Windows原生 Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py \
  tests/unit/test_hk_corporate_actions.py \
  tests/unit/test_hk_corporate_action_implementation.py -q
→ 150 passed, 20813 warnings in 52.54s

D:\Miniforge3\python.exe -m ruff check <5个改动生产/测试文件>
→ All checks passed!

D:\Miniforge3\python.exe -m mypy \
  src/quant/domain/schemas.py src/quant/domain/__init__.py \
  src/quant/data/hk_corporate_action_implementation.py
→ Success: no issues found in 3 source files
```

warnings为既有Pandera/Polars deprecation和worktree pytest cache权限提示，不是断言失败。scoped
`git diff --check`通过，仅显示既有CRLF提示。

独立复验另在WSL Miniforge base运行对应定向组：`125 passed`，Ruff/mypy通过；`findmnt`确认项目位于
`/mnt/f` DrvFS，因此只作为Linux兼容反馈，不替代ext4 Gate。

## 4. 边界与下一步

本报告关闭：`VerifiedImplementedHkCorporateActionSet` 来源无关开发合同。它证明未来approved adapter必须满足
的接口、fresh identity与retained语义，不证明当前已有真实licensed implementation adapter。

仍开放：

1. `M1_HK_CA_P1_PRE_B_HK行情AvailabilityReceiptV3任务单.md`：seed/request/HKEX supplement逐key
   availability与finalize v3；
2. 真实HK implementation source adapter与retained格式验收；
3. dividend再投资日、同日事件顺序、FX、RIGHTS与归一化锚点等total-return业务裁定；
4. 01065.HK licensed HKEX evidence、HK60 formal finalize、WSL2/ext4与M1 Gate。

因此准确状态为：**实施事实开发合同通过；bar capability与M1正式Gate未通过。**

