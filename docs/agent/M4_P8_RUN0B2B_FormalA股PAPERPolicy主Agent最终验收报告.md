# M4 P8 RUN-0B2B：Formal A股 PAPER Policy 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅 development 工程合同）**

## 1. 结论

RUN-0B2B 已建立唯一、版本化、只读的 A股 formal PAPER policy/config loader。它只接受 fresh exact
`VerifiedPaperRuntimeEnvironment`，从 allowlisted selector 推导项目内 formal policy，验证嵌套 TradingConfig、
SH/SZ+CNY费用、风险窗口、store URI、最小金额与adapter/fill/fault/finality/clock版本后签发process-local exact
capability。实现、自测、全新独立初验和主验均通过，可作为下一包 formal gateway/store/service factory 的
policy 输入。

该结论不创建真实 formal runtime，不代表 WSL2/ext4、scheduler、28日soak或M4 Gate通过。

## 2. 主验核对

- formal值全部来自独立 `paper_a_share_v1.toml` PAPER模拟SSOT，不在运行时读取research/example配置；
- public loader无caller path/hash/mapping/classification入口，example/development/unknown selector在业务读取前拒绝；
- 唯一formal mint位于私有closure，创建函数随后删除，process-local key不在模块表面；`__all__`和import-star
  exact只有错误、capability、load、verify四项；
- policy source使用anchored open-instance，绑定project/parent/file物理身份、单链接regular file与内容；签发前
  fresh复核runtime及held内容；
- TradingConfig/store URI、SH/SZ cost schedule、CNY `1.00` minimum、2026窗口和所有版本selector exact闭合；
- existing verifier先验attestation，再fresh调用同一public loader并exact compare；失败稳定脱敏且零状态写入。

独立初验新增签发中同bytes换inode与递归hostile异常图，均稳定fail closed；内部领域builder虽可供测试
monkeypatch，但不在`__all__`/import-star表面且不能签formal capability，不构成额外public mint。

## 3. 验证证据

- Windows实现/独立：`27 passed, 1 skipped`，Ruff/mypy/cold import PASS；唯一skip为当前symlink权限；
- WSL base/DrvFS：`28 passed`，Ruff/mypy/cold import PASS；
- 主Agent复核formal正例、同bytes换inode、whole-rehash旧attestation、public surface四节点（含参数化）→
  `8 passed`；Ruff与mypy两文件PASS；
- 白名单diff check PASS，未联网、未建root/DB/journal、未add/commit。

## 4. 保留边界

- 当前WSL为wslfs/DrvFS，不是ext4；纯合同模拟formal环境不替代actual WSL2/ext4验证。
- policy只声明fill/fault等版本，具体adapter/factory属于下一包；TargetLoader等待M3 G7A，
  LedgerContextProvider等待verified calendar/settlement来源。
- 不得据此注册scheduler或启动soak；M4继续`WAITING_FOR_SOAK_EVIDENCE`。
