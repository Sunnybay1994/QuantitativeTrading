# M4 P5-P0B 共享 Canonical Wire 实现报告

## 交付摘要

- 新增 `quant.domain.canonical_wire` 作为无 execution/backtest 依赖的公共低层原语，并由
  `quant.execution.wire` 与 `quant.backtest.ledger_wire` 单向依赖。
- 新增 `quant.execution.wire`，统一 P4/P5 command、event、aggregate 的严格 canonical 编解码与身份复验。
- 新增 `quant.backtest.ledger_wire`，冻结 ledger entry/state v1；完整持久化 checkpoint 中 position、cash、
  pending settlement、trading credit、entitlement、action 与 command projection。
- `quant.execution.service` 已删除三类私有 wire 字段实现，改为调用公共 codec；stage/counter 自身格式保持原状。
- 新增 execution/ledger 专用对抗测试；P4 重构前 fixture 的三组 golden SHA-256 固化为回归断言。
- 本次没有修改 store 或 migration，没有写入正式 G1 目录、journal、候选映射或发布根。

## 设计理由

P5 恢复必须从持久化 bytes 重建自证领域对象，而不是在 service、recovery 和 ledger 各复制一套 JSON 字段。
公共成对 codec 使 P4 写入与 P5 读取共享同一 SSOT；strict parse + canonical byte equality 同时拒绝重复键、
宽松 JSON、非唯一文本和未来 schema，领域构造器则重新证明 identity 与跨字段约束。

## 验证记录

Windows 原生（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）：

- `python -m ruff check`：目标为三个生产文件和两个新增测试文件，`All checks passed!`。
- `python -m mypy`：目标为三个生产文件，`Success: no issues found in 3 source files`。
- `python -m pytest -p no:cacheprovider --basetemp=<独立 artifacts 路径>`：新增 wire/ledger、现有
  execution service，返工后 `56 passed in 4.86s`。

Windows 首轮 pytest 暴露两个主机环境问题：site-packages 中旧 `quant` 抢占当前源码，以及系统默认 pytest
临时目录 ACL 拒绝访问。显式设置当前 worktree `PYTHONPATH` 并使用独立 `--basetemp` 后通过；没有修改环境、
正式数据或测试语义。

WSL Miniforge base（`/home/mabw/miniforge3/bin/conda run --no-capture-output -n base`）：

- 同一范围 Ruff：`All checks passed!`。
- 同一范围 mypy：`Success: no issues found in 3 source files`。
- 同一范围 pytest，临时文件位于 `/tmp/quant-p0b-wsl-20260802g`：`56 passed in 3.18s`。

以上结论是 Windows/WSL 开发契约定向验证通过；DrvFS 上的 WSL 结果不等于 ext4/Linux Gate。

## 独立初验返工记录

- 现象：初验发现任意字符串 schema 被误报 `WIRE_VERSION_UNSUPPORTED`；被翻译的 Python 异常仍可从
  `WireError.__context__` 找回；ledger 依赖 execution wire 私有 helper。
- 根因：版本分类过宽；`from None` 只抑制 traceback 展示而没有清空活动异常上下文；公共原语最初位于
  execution 消费者层。
- 应遵循规则：同 family 的正规范未来版本才是 unsupported；异常翻译必须在离开 `except` 后发生；
  共享原语必须位于依赖图下层。
- 新增测试：schema 参数矩阵、parser/constructor `TOKEN` 对抗异常链断言、AST 依赖方向守卫。
- 通过条件及结果：P4 三组 golden hash 保持不变，Windows/WSL Ruff 与 mypy 通过，双平台 pytest 均为
  `56 passed`；现重新提交独立初验。

## 尚未解除的阻塞

- P0C ledger context/checkpoint/store schema 与 P4 transaction closure 尚未实现。
- `recover_local_state` 与 broker reconciliation 尚未实现，因此 P5 仍暂停。
- 正式 G1、Linux Gate、正式 PAPER soak 与 M4 Gate 均不由本开发契约结论替代。
