# M1 HK CA P1 PRE-B R3 原始目录锚存活性闭包独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的全新独立复验 Agent  
结论：**FAIL；不得进入主 Agent 终验或正式 v3 migration**

## 1. 复验边界

本轮完整阅读了项目 `AGENTS.md`、`.ai/README.md`、Availability Receipt v3 任务单 §12、R2 FAIL
报告和 R3 返工交付报告；生产代码与实现者测试全程只读。没有联网，没有读取或写入正式
02983/01065 data、journal 或候选目录，没有 add/commit。独立探针只使用系统临时目录中的 synthetic
fixture；worktree 唯一新增文件是本报告。

## 2. 已确认通过的 R3 项

1. `_DirectoryAnchor.close()` 已成为 terminal 状态；`_ReadAnchors.assert_namespaces()` 先遍历 journal、
   seed、raw、clean 的 `assert_live()`，再检查 path namespace，不再用 path 重开结果替代已显式关闭的锚。
2. public load/verify 在签发前关闭 journal、seed、raw、clean 单锚或整组 anchors 的实现者矩阵均稳定返回
   `HK_BAR_VERIFY_FAILED`；后代目录和单文件 descriptor/handle 被关闭也拒绝。
3. 独立微型探针确认：descriptor/handle 编号复用到**不同目录对象**时，两平台均以 `_AnchorViolation`
   拒绝；后代目录和单文件关闭分别以底层 `OSError` 拒绝，进入 public 边界后由既有异常脱敏闭包转为稳定码。
4. capability 先构造、`finally` 关闭前直接抛出新的 `OSError` 的独立探针在 Windows 与 WSL 均返回
   `HK_BAR_VERIFY_FAILED`，最终异常的 `__cause__`/`__context__` 均为 `None`，零 capability 逃逸。
5. R1 root ABA、R2 hostile exception graph、whole-rehash、legacy v1/v2 隔离、四文件事务/no-clobber、
   symlink/reparse 和 source closure 均包含在三文件定向全组中并保持绿色。

上述结果关闭了 R2 报告中的“显式 `anchors.close()` 后按 path 重开仍签发”原始复现，但第 3 节的全新
same-file descriptor reuse 反例仍违反 §12.2 的原始锚存活性不变量。

## 3. 阻塞问题

### 3.1 [P1] 原 descriptor 关闭后，同编号重开同一物理目录仍被当作原锚接受

**现象**

独立探针在 retained/clean 全部读取完成、`_capability_attestation` 的 live assertion 前执行：

1. 外部关闭本次窗口的 raw root 原 fd/handle；
2. 立即重新打开同一个 raw root 物理目录；
3. 操作系统复用刚释放的同一 descriptor/handle 编号；
4. 继续原 public load 或 verify。

Windows 与 WSL/DrvFS 均成功签发或接受 `VerifiedHkBarBundle`：

```text
Windows: REUSE_IDS load 944 944;  SAMEFILE_REUSE_ACCEPTED load
Windows: REUSE_IDS verify 1236 1236; SAMEFILE_REUSE_ACCEPTED verify
WSL:     REUSE_IDS load 8 8;      SAMEFILE_REUSE_ACCEPTED load
WSL:     REUSE_IDS verify 8 8;    SAMEFILE_REUSE_ACCEPTED verify
```

同一轮对照探针把同编号重开到不同目录，两平台均拒绝；因此该结果不是探针没有触发，而是实现只识别
identity 漂移，不能识别“原 open 已结束、同一编号产生了新的 open instance”。

**根因**

`_DirectoryAnchor.assert_live()` 对 POSIX 原 fd 执行 `os.fstat(fd)` 并比较 `(st_dev, st_ino, type)`；Windows
对 handle 执行 `GetFileInformationByHandle` 并比较 `(volume, file_index, attributes)`。这些检查能证明
**当前**编号指向创建时的同一文件系统对象，却不能证明它仍是创建时那次 open 的原始 descriptor/handle。
外部 close 后重开同一对象，只要编号也被复用，全部 identity 比较和后续 path namespace 比较都会通过。

因此当前顺序虽然是“descriptor identity → path namespace”，但第一个先验本身仍不足以证明任务单 §12.2
要求的“不可替换的原始 descriptor/handle 从读取窗口保持到 capability 签发完成”。

**被破坏的不变量**

任务单 §12.2 要求原始 root、后代目录和文件 descriptor/handle 不可替换；外部关闭、复用、缺失或漂移
都必须 fail closed。关闭后重开同一物理目录仍是新的 open instance，不是原 descriptor 的持续存活，故
不得仅因文件 identity 未变而继续签发 capability。

**最小复现**

1. 用 `_published_v3` 在系统临时目录生成 synthetic v3；
2. 捕获 fresh `_ReadAnchors`，包装 `_capability_attestation`；
3. 在包装器内关闭 `captured.raw._fd` / `_handle`；
4. 立即以相同 flags 重开 `captured.raw.path`，确认新编号等于旧编号；
5. 调用原 attestation。当前 load 与 verify、Windows 与 WSL 均成功。

**应遵循规则与最小返工范围**

- live proof 必须绑定创建时那次 open 的 instance，而不只是 descriptor 数值与文件 identity；同编号重开
  同一对象也必须可检测并拒绝。
- journal、seed、raw、clean root 以及实际读取过的后代目录/文件应使用同一 open-instance continuity
  机制；不能退回 path reopen，也不能只新增另一份同样可被编号复用绕过的 identity 比较。
- 保持现有“全部 live proof 先于全部 path namespace proof”的顺序、finally close 零 capability、公开错误
  脱敏、v3 schema/availability/四文件事务/legacy 语义不变。
- 返工应限制在 anchor 生命周期证明及其测试，不扩大到正式 migration 或真实数据。

**新增测试与通过条件**

- 在 load 与 verify 两个 public 边界，分别对 root、一个后代目录和一个 exact file 做
  `close → same object reopen → same descriptor number`，必须稳定返回 `HK_BAR_VERIFY_FAILED`；Windows 与
  POSIX 均须覆盖。
- 测试必须先断言旧、新 descriptor/handle 数值相同且文件 identity 相同，避免把编号未复用或不同对象
  拒绝误报为通过。
- 保留并继续通过 `close → different object reopen`、单锚/整组 close、close failure、R1 ABA、R2 异常图、
  whole-rehash、legacy/no-clobber 全组。
- 返工后由未参与返工的另一全新独立上下文复验；PASS 后才进入主 Agent 终验。

## 4. 验证结果

### Windows 原生 Miniforge

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
  tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
153 passed, 1 skipped

ruff（4 个生产文件 + 3 个测试文件）: All checks passed!
mypy（4 个生产文件）: Success: no issues found in 4 source files

独立 same-file public probe: load/verify 均 SAMEFILE_REUSE_ACCEPTED
独立 different-file root probe: DIFFERENT_ROOT_REUSE_REJECTED
独立 descendant/file close probe: 均拒绝
独立 finally pre-close exception probe: HK_BAR_VERIFY_FAILED，cause/context=None
```

唯一 skip 是既有平台条件用例，不影响 synthetic v3 合同矩阵。

### WSL Miniforge base

```text
同组三文件 pytest: 154 passed
ruff: All checks passed!
mypy: Success: no issues found in 4 source files

独立 same-file public probe: load/verify 均 SAMEFILE_REUSE_ACCEPTED
独立 different-file root probe: DIFFERENT_ROOT_REUSE_REJECTED
独立 descendant/file close probe: 均拒绝
独立 finally pre-close exception probe: HK_BAR_VERIFY_FAILED，cause/context=None
```

当前 worktree 实际位于 `/mnt/f` DrvFS；这些结果只属于 Windows/WSL 双平台开发合同反馈，不是 ext4/Linux
Gate 证据。

## 5. 裁定与边界

R3 已修复显式 terminal close、不同对象复用、后代/file descriptor 关闭和 close-failure capability 逃逸，
且常规定向回归全部绿色；但 same-file descriptor reuse 证明原 open-instance continuity 仍未建立。该问题直接
违反本轮唯一高风险冻结不变量，因此独立复验为 **FAIL**。

本结论不改变既有业务数据，也不否定已通过的开发态 v3 schema/availability/事务回归。正式 v3 migration、
真实 HK 公司行动、01065/HK60、ext4 与 M1 Gate 均未由本轮关闭。
