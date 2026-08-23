# M4 P8 RUN-0B2C：Formal Broker Policy Binding 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅 development 工程前置）**

## 1. 验收结论

RUN-0A 的 exact formal runtime environment 与 RUN-0B2B 的 exact formal A股 PAPER policy 现可通过唯一
process-local capability 进行 fresh 绑定。B1 development descriptor 未放宽，本包未创建或打开 broker root、
SQLite、gateway、account、runner、scheduler 或 soak，也未产生正式 PAPER 运行能力。

## 2. 主验核对

- runtime existing preflight 的真实接口是成功返回 `None` 的命令式 verifier；任务书已纠正为“成功后继续使用原
  exact environment”，没有虚构返回 capability。
- policy existing verifier 的返回值要求 exact type 且 exact-equal；cross capability、session、nested identity、
  cost/version/FX 漂移均 fail closed。
- formal mint 位于已删除创建器的私有 closure；`__all__` 只含 error/type/bind/verify，未暴露 generic signer、key、
  builder或factory。
- 失败稳定脱敏、cause/context为空；模块自身无文件、DB、socket、日志、网络或墙钟 I/O。
- 独立初验补测 runtime void 调用、runtime失败时policy零调用、hostile不同policy返回、递归异常图及冷导入，结论PASS。

## 3. 验证证据

- 实现者：Windows focused `13 passed`，上游合流 `40 passed, 1 skipped`；WSL base合流 `90 passed`；两平台
  Ruff/mypy/cold-import通过。
- 独立初验：Windows binding+policy `40 passed, 1 skipped`、runtime `19 passed, 30 skipped`；WSL base
  `90 passed`；两平台静态检查通过。
- 主 Agent 以隔离 worktree `PYTHONPATH` 重跑 focused：`13 passed in 7.18s`；Ruff与production mypy通过。
- 定向 `git diff --check` 无错误。

主验第一次未显式隔离 `PYTHONPATH` 时错误导入根工作树模块并在collection阶段失败；改用本worktree `src` 后
定向套件全绿。该结果属于调用环境错误，未据此修改产品代码或测试。

## 4. 保留边界与下一步

当前 WSL 路径为 wslfs/DrvFS，不是 ext4。M4 继续保持 `WAITING_FOR_SOAK_EVIDENCE`；formal runner、注册、
真实28日 soak均未开始。

下一包必须先冻结 formal PAPER account SSOT/config/descriptor loader；之后才可实现 formal store initializer/
opener与 durable gateway factory/snapshot port，再进入 LedgerContext/Service 装配。禁止绕过 account SSOT 直接建
正式 store 或 gateway。
