# M1 HK CA P1 PRE-B R4 descriptor open-instance continuity 返工交付报告

日期：2026-08-09

角色：实现 Agent

状态：实现与双平台定向自测完成；等待未参与 R4 的全新独立上下文复验，不宣布 Gate。

## 1. 失败闭环

- 现象：R3 仅以 descriptor 数值和 file identity 验证原锚。关闭原 fd/handle 后，对同一物理对象
  重新 open 并复用相同整数编号，load/verify 仍可签发 capability。
- 根因：`fstat`、file-id、descriptor 数值和 path identity 只能证明当前编号指向同一文件系统对象，
  不能证明它仍属于创建锚时的 kernel open instance/open file description。
- 应遵循规则：每个 root、后代目录和 file 原 descriptor 必须持有同次 duplicate primitive 产生的
  private duplicate；签发前除 identity 外还要证明原件与 duplicate 仍属于同一 open instance。
  任一原件或 duplicate 被关闭、同/异对象重开、编号复用、API 不支持或恢复失败均 fail closed。
- 最小复现：在 `_capability_attestation` 的最终 live assertion 前关闭 raw anchor 的 root、后代目录或
  file 原 descriptor；立即以相同 flags 重开同一对象，并断言新旧整数编号及 file identity 均相同。
- 新增测试：load/verify × root/descendant/file 的 original same-object reuse；load/verify × 三层 ×
  private duplicate same/different-object reuse；POSIX status flag 共享/恢复及 offset 不漂移；Windows
  duplicated handle 与 reopened same-file handle 的内核对象比较；正常 close 全量无泄漏。
- 通过条件：上述矩阵稳定返回 `HK_BAR_VERIFY_FAILED`，R1–R3 ABA、异常图、close/close-failure、
  whole-rehash、legacy/no-clobber 回归不退化，Windows 与 WSL base 定向 Ruff/mypy/pytest 通过。

## 2. 平台原语与最小实现

实施前真实探测结果：

- WSL Miniforge base：`F_DUPFD_CLOEXEC` 可用；在原 fd 切换 `O_NONBLOCK` 后 private duplicate
  同步可见，恢复后双方 flags 精确回到初值。
- Windows：`DuplicateHandle` 可用；`CompareObjectHandles` 由 `KernelBase.dll` 导出。

实现内容：

- POSIX 为每个 root、实际打开的后代目录及 file 使用 `F_DUPFD_CLOEXEC` 建立 private duplicate，
  保存初始 `F_GETFL`。每次 live proof 临时翻转原 fd 的 `O_NONBLOCK`，要求 duplicate 同步可见、
  其他 status flags 不变，并在所有路径精确恢复双方初值；任何读取、设置或恢复异常均拒绝。
- Windows 为同一三层 handle 使用 `DuplicateHandle(..., DUPLICATE_SAME_ACCESS)` 建立 private
  duplicate；每次 live proof 同时验证双方 file identity，并要求 `KernelBase.CompareObjectHandles`
  返回 true。API 缺失、无效 handle 或 false 均拒绝，不以 file-id 降级。
- terminal close 尝试关闭所有 private duplicate 与 original descriptor；Windows `CloseHandle`
  现检查返回值，部分关闭失败继续由既有 finally 逻辑阻止 capability 逃逸。
- duplicates 仅保存在 private anchor 状态中，不进入 capability、receipt、异常或 repr；R2 anchored
  read、R3 整组 live-first/path-second 顺序和最终签发点保持不变。

本轮未改变 v3 schema、availability 业务语义、四文件发布合同、legacy v1/v2、HMAC、whole-rehash、
no-clobber 或公开异常码。

## 3. 验证结果

R4 专项矩阵，两平台各 `20 passed`：

```text
original: load/verify × root/descendant/file × same-object same-number reopen
private duplicate: load/verify × root/descendant/file × same/different-object reuse
primitive: POSIX flag/offset restore 或 Windows CompareObjectHandles
cleanup: every original/private duplicate closed
```

Windows 原生 Miniforge：

```text
ruff check <PRE-B 白名单 4 个生产文件 + 3 个测试文件>
All checks passed!

mypy <PRE-B 白名单 4 个生产文件>
Success: no issues found in 4 source files

pytest tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
       tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
173 passed, 1 skipped
```

WSL Miniforge `base`，路径 `/mnt/f/...`（DrvFS）：

```text
ruff check <同一白名单>
All checks passed!

mypy <同一生产文件白名单>
Success: no issues found in 4 source files

pytest tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
       tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
174 passed
```

Windows 的单个 skip 是平台条件用例；WSL DrvFS 结果不等于 ext4 Gate。

## 4. 边界与剩余事项

- 未执行网络请求，未读取、修改或迁移正式 02983/01065 data、journal 或候选目录。
- 未 add、未 commit；worktree 中全部既有无关脏文件和未跟踪产物保持原样。
- 当前仅为 R4 实现者自测完成；必须由未参与 R4 的全新独立上下文复验，PASS 后才进入主 Agent 终验。
- 正式 v3 migration、真实 HK 数据、01065、HK60、ext4 与 M1 Gate 均未由本轮关闭。
