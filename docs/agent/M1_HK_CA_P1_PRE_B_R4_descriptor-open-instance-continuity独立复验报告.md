# M1 HK CA P1 PRE-B R4 descriptor open-instance continuity 独立复验报告

日期：2026-08-09  
角色：未参与 R4 实现的全新独立复验 Agent  
结论：**PASS；可进入主 Agent 终验，但不代表正式 v3 migration、真实 HK 数据或 M1 Gate 已通过**

## 1. 复验边界

本轮完整阅读了 Availability Receipt v3 任务单 §11–§13、R3 FAIL 报告、R4 返工交付报告，以及当前
`hk_history_backfill.py` 的 root、后代目录、文件锚实现和 R4 实现者测试。生产代码与实现者测试全程只读；
worktree 唯一新增文件是本报告。没有联网，没有读取或写入正式 02983/01065 data、journal、候选目录，
没有 add/commit。独立探针仅使用系统临时目录中的 synthetic fixture，并在进程结束前清理。

## 2. 合同逐项裁定

1. **同次 open-instance 证明：PASS。** POSIX 的 root、实际读取的后代目录和文件均以
   `F_DUPFD_CLOEXEC` 保存 private duplicate，并以共享 `O_NONBLOCK` status flag 的同步切换及精确恢复
   证明同一 open file description；Windows 对同三层使用 `DuplicateHandle`，并以
   `CompareObjectHandles` 证明同一内核 file object。两平台同时保留原 descriptor/handle、duplicate 和
   file identity，不以编号、inode/file-id 或 path identity 单独替代 open-instance proof。
2. **R3 same-object/same-number 反例：PASS。** 实现者矩阵已覆盖 load/verify × root/descendant/file；
   独立探针另以“先完整读取后代和文件，再关闭 raw root original，对同一物理 root 立即重开并确认整数编号
   复用、identity 相同”的组合验证。Windows 的 `CompareObjectHandles` 返回 false，POSIX 的共享 flag
   proof 不同步，二者均拒绝。
3. **private duplicate 与平台失败语义：PASS。** duplicate 被关闭并以 same/different object 复用时，
   identity 或 open-instance proof 拒绝。独立 POSIX 探针在成功切换 flag 后令第一次恢复 `F_SETFL` 抛出
   `HOSTILE_RESTORE_MARKER`，live assertion fail closed；public load/verify 均只返回
   `HK_BAR_VERIFY_FAILED`。独立 Windows 探针令 `CompareObjectHandles` 包装层抛
   `HOSTILE_COMPARE_MARKER`，public load/verify 同样 fail closed。不存在 file-id 降级路径。
4. **签发顺序与异常图：PASS。** `_ReadAnchors.assert_namespaces()` 先对四类 root 及全部 retained
   descendant/file 运行 live proof，再做 path namespace proof；capability attestation 位于最终 live proof
   之后、`finally: anchors.close()` 之前。close/restore/CompareObjectHandles 的 hostile marker 在 public
   load/verify 均未进入异常字符串、格式化 traceback、`__cause__` 或 `__context__`；任一失败均为零
   capability。
5. **清理与泄漏：PASS。** `close()` 为 terminal/idempotent，并在某一 close 失败后继续尝试关闭其余
   original/private descriptors。独立 Windows 探针让第一个 handle 在物理关闭后抛异常，仍确认所有 root、
   descendant、file originals/duplicates 均已无效；Windows 50 次和 POSIX 50 次完整 open/read/assert/close
   前后进程 handle/fd 数一致。
6. **既有合同无回退：PASS。** v3 schema、exact availability、HKEX retained metadata、source closure、
   four-file no-clobber/rollback、whole-rehash、legacy v1/v2 隔离、R1 root ABA、R2 异常图和 R3 terminal
   close 回归均包含在三文件定向全组并保持绿色。

## 3. 实现者未直接使用的独立对抗证据

### 3.1 POSIX restore failure + public exception graph

在临时目录创建 root/descendant/file 锚；完成一次读取后，包装 `fcntl.fcntl`：首次 `F_SETFL` 正常切换，
第二次（恢复）抛 `HOSTILE_RESTORE_MARKER`。结果：

```text
POSIX_INDEPENDENT_R4_PROBES_PASS
POSIX_PUBLIC_RESTORE_EXCEPTION_GRAPH_PASS
```

`assert_live()` 返回 `_AnchorViolation`；load 与 verify 均返回唯一稳定码，cause/context 为 `None`，格式化
traceback 不含 marker。探针随后用原生调用恢复 flag 并关闭锚，fd 计数回到基线。

### 3.2 Windows CompareObjectHandles hostile + partial teardown

独立组合先关闭 root original handle、同物理 root 重开并确认 same integer/same file identity，再确认
`CompareObjectHandles(reopened, private_duplicate) == false` 且 `assert_live()` 拒绝。另令 compare 包装层
抛 hostile marker，并令第一个 `_win_close_handle` 在物理关闭后抛异常；结果：

```text
WINDOWS_INDEPENDENT_R4_PROBES_PASS
WINDOWS_PUBLIC_EXCEPTION_GRAPH_PASS
```

load/verify 公开异常图无 marker；partial teardown 后枚举的 root、descendant、file original/private handles
全部无效，进程 handle 计数回到基线。

## 4. 双平台定向验证

### Windows 原生 Miniforge

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
  tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
173 passed, 1 skipped

ruff check <4 个生产文件 + 3 个测试文件>
All checks passed!

mypy <4 个生产文件>
Success: no issues found in 4 source files
```

唯一 skip 是既有平台条件用例。

### WSL Miniforge base

```text
同组三文件 pytest: 174 passed
ruff: All checks passed!
mypy: Success: no issues found in 4 source files
```

当前 worktree 解析到 `/mnt/f/...` DrvFS；该结果是 WSL/base 双平台开发反馈，不是 ext4/Linux Gate 证据。

## 5. 最终裁定与剩余边界

R4 已建立任务单 §13 冻结的 descriptor open-instance continuity：original 或 private duplicate 的
same-object/same-number reopen 不再绕过 root、descendant 或 file 的最终 live assertion；restore/API/
teardown 失败均 fail closed，且 capability 签发、异常图脱敏和资源清理闭包成立。因此本轮独立复验为
**PASS**，可以进入主 Agent 终验。

本结论只关闭开发态 PRE-B R4 合同。正式 v3 migration、真实 02983 公司行动闭包、01065/HK60、ext4
平台 Gate 和 M1 正式完成仍需各自后续证据，未由本报告宣称通过。
