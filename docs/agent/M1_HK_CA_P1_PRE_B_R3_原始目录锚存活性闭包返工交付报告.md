# M1 HK CA P1 PRE-B R3 原始目录锚存活性闭包返工交付报告

日期：2026-08-09

角色：实现 Agent

状态：实现与双平台定向自测完成；等待未参与 R3 的全新独立上下文复验，不宣布 Gate。

## 1. 返工闭环

- 现象：R2 独立复验在 retained/clean 全部读取后、capability 签发前调用
  `anchors.close()`，旧实现仍可按路径重新取得 identity 并签发
  `VerifiedHkBarBundle`。
- 根因：目录 namespace 复验没有把“读取窗口使用的原始 fd/handle 仍存活且仍绑定原对象”
  作为先决条件；`close()` 也不是 terminal 状态。
- 应遵循规则：每次 namespace assertion 必须先验证整组原始 root、后代目录和文件
  descriptor/handle 的存活性与创建时 identity，再检查路径 namespace；任何关闭、复用、
  缺失或 identity 漂移均 fail closed。capability 只能在最后一次 live assertion 之后、
  `finally` 关闭 anchors 之前构造；关闭失败时不得返回已构造 capability。
- 最小复现：在 `_capability_attestation` 前关闭一个 root anchor 或整组 anchors；另以
  `os.close`/`CloseHandle` 外部关闭原 descriptor，并尝试让同一编号绑定另一目录。
- 新增测试：load/verify × journal/seed/raw/clean/整组关闭；root descriptor 外部关闭与复用；
  后代目录/file descriptor 关闭；单 anchor terminal/idempotent close；finally close 抛错后
  零 capability 且稳定脱敏。
- 通过条件：上述矩阵稳定返回 `HK_BAR_VERIFY_FAILED`；R2 ABA、异常图、whole-rehash、
  legacy/no-clobber 回归继续绿色；Windows 与 WSL base 定向 Ruff/mypy/pytest 通过。

## 2. 最小实现

- `_DirectoryAnchor` 保留所有实际读取过的 root、后代目录和文件原始 fd/handle 及创建时
  identity，直到整组关闭；`close()` 设置不可逆 terminal closed 状态并尽力关闭全组资源。
- `assert_live()` 直接对原 fd 执行 `fstat`，或对原 Windows handle 执行 identity 查询；
  `_ReadAnchors.assert_namespaces()` 先完成四个 root 的整组 live 检查，再执行 path namespace
  检查，禁止以重开路径替代原锚。
- POSIX 读取继续使用 anchored component walk；Windows 读取保留逐级目录/file handle，并从
  已打开 file handle 读取内容。
- capability 的唯一构造点位于最后一次 `anchors.assert_namespaces()` 之后；`finally` 中
  `anchors.close()` 的任何失败覆盖待返回结果并统一为稳定公开错误。
- DrvFS 上持有后代/file 锚可能直接阻止 rename；ABA 测试统一接受“平台阻止替换”或“替换成功后
  验证器拒签”两种安全结果，不把未发生的攻击误报为验证器放行。

本轮未改变 v3 schema、四文件发布合同、availability 业务语义、legacy v1/v2 语义、HMAC、
whole-rehash 或公开错误码集合；未修改 history/bar 之外的业务范围。

## 3. 验证证据

Windows 原生 Miniforge：

```text
ruff check <PRE-B 白名单 4 个生产文件 + 3 个测试文件>
All checks passed!

mypy <PRE-B 白名单 4 个生产文件>
Success: no issues found in 4 source files

pytest tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
       tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
153 passed, 1 skipped
```

WSL Miniforge `base`，路径 `/mnt/f/...`（DrvFS）：

```text
ruff check <同一白名单>
All checks passed!

mypy <同一生产文件白名单>
Success: no issues found in 4 source files

pytest tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
       tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
154 passed
```

首轮 R3 专项矩阵在两平台均为 `17 passed`；补充 close-failure 两例后已纳入上述最终全组。
Windows 的单个 skip 是平台条件用例；WSL DrvFS 结果不是 ext4 Gate 证据。

## 4. 边界与剩余风险

- 未执行网络请求，未读取或迁移正式 02983/01065 数据，未写正式 data/artifacts/journal。
- 未暂存、未提交；worktree 既有无关脏文件与未跟踪产物均保留。
- 本报告仅证明 PRE-B R3 实现者定向开发合同；仍需全新独立上下文复验，随后才可进入主 Agent 终验。
- Linux ext4 平台 Gate、真实 HK 数据、01065、HK60 与 M1 Gate 均未由本轮关闭。
