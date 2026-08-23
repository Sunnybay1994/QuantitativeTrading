# M1-HK60-V3M-P0 显式 v3 finalize 执行外壳独立复验报告

日期：2026-08-09  
角色：未参与实现的全新独立复验  
结论：**FAIL；dual-file retained loader 未闭合已打开文件的内容漂移/ABA 窗口**

## 1. 范围与隔离

本轮完整核对任务单、PRE-B R4 主验、实现交付报告，以及当前 CLI、dual-file loader、锚实现和两个白名单
测试文件。生产代码与实现者测试保持只读；本报告是唯一新增文件。所有新增对抗只在系统临时目录执行，未读取
或写入正式 HK60 plan、raw、journal、clean、`data/legacy` 或正式 artifacts，未构造 connector，未发起网络请求，
未 add/commit。

本结论只评价 fixture-only V3M-P0 工程合同；不评价正式 02983/01065 provenance、licensed HKEX source、
V3M-P1 migration、HK60、HK 复权、ext4 或 M1 Gate。

## 2. 逐项复验结果

### 2.1 通过项

- CLI 的 v3 raw+metadata 必选、与 legacy/recover/retry 互斥，以及 metadata 在非 v3 模式拒绝，均在读取 plan
  前收敛为 `HK_HISTORY_PLAN_CONFLICT`。
- v3 成功路径只向 `finalize_hk_history` 传 exact bundle，不传 raw-only 参数；stdout 区分
  `hk-history-finalize-v3`，并包含 rows、bundle id 与 metadata identity。
- verifier/loader/finalize hostile 异常映射为公开固定码；实现测试覆盖 verify 失败时 finalize/connector 与输出
  副作用为零。
- same-file/hardlink、symlink/reparse、path replacement、角色 root 重叠、plan 位于可写 root、legacy 混配、
  partial 四文件、异 bytes exact retry、no-clobber 与 clean 非全局 rollback 边界均有直接回归并通过。
- 独立新增 Windows handle 对抗：分别关闭 raw original handle 与 metadata private duplicate，再把同一物理文件
  重开到相同整数 handle；两次均确认 `SAME_NUMBER_REOPEN=True`，loader 均稳定拒绝为
  `HK_HISTORY_REFERENCE_INVALID`。这证明 PRE-B R4 的 original/private kernel-object continuity 在本 loader 中
  被实际调用，而不是只比较 file-id。

### 2.2 阻断问题：内容漂移与 ABA 可逃逸

现象：`load_verified_hkex_retained_bundle_for_finalize` 读完 raw/metadata 后，verifier 窗口内若原地改写任一
已打开普通文件，loader 仍返回 verifier 的 exact bundle。即使改写后恢复原 bytes 的 ABA，也同样返回成功。

独立复现结果：

```text
Windows:
RAW_DRIFT_ESCAPED=True
METADATA_DRIFT_ESCAPED=True
RAW_ABA_ESCAPED=True
METADATA_ABA_ESCAPED=True

WSL base / wslfs:
WSL_RAW_DRIFT_ESCAPED=True
WSL_METADATA_ABA_ESCAPED=True
```

最小复现：创建不同的 `raw` 与 `metadata` 普通文件；把
`verify_hkex_daily_quotation_retained` 替换为一个返回 sentinel 前通过同一路径 `write_bytes` 原地改写 raw 或
metadata 的函数；调用公开 loader。非 ABA 用例保留新 bytes，ABA 用例随后写回原 bytes。四个 Windows 用例和
两个 WSL 代表用例均返回 sentinel，没有抛出 `HK_HISTORY_REFERENCE_INVALID`。

根因：`src/quant/data/hk_history_backfill.py` 的 loader 在首次 read-once 后只保存 `(volume, file-index)` 或
`(device, inode)`；verifier 返回后只调用 `anchor.assert_namespace()` 和 `_path_file_identity()`。这些检查证明
路径、物理对象以及 original/private descriptor open-instance continuity，却没有从仍持有的同一打开实例复核
内容长度/摘要。原地写入不改变 inode/file-id，因此 raw/metadata bytes 可以在完整验证窗口内漂移；恢复 bytes
的 ABA 也没有任何可观察内容锚。

被破坏规则：任务单 §3 明确要求 raw/metadata 的“bytes 漂移”在 finalize 前稳定拒绝，并要求两文件保持
same-window anchored read。当前实现只能证明对象身份闭包，不能证明传给 verifier 的 bytes 在窗口结束前仍是
该对象的稳定内容。

影响：这不是测试完整性的小缺口。攻击或并发写入可让 verifier 审核旧 bytes，但 loader 返回时显式输入路径
已经包含另一份 raw 或 metadata；随后 CLI 仍可能进入 finalize。故 V3M-P0 的 fresh exact-bundle 前置条件未成立。

## 3. 必须返工与新增回归

返工应保持在任务单既有白名单，不修改 HKEX schema/parser 或 finalize 业务语义：

1. raw 与 metadata 首次 read-once 时记录 exact payload 长度与 SHA-256；
2. verifier 返回后、任一 result 逃逸前，从仍持有且通过 original/private open-instance continuity 的同一文件
   实例重新读取并核对长度/摘要；不得通过路径重新打开来代替 held descriptor/handle 复核；
3. 两个文件必须先完成 live/open-instance 检查，再完成内容复核与 namespace/identity 复核，close 失败继续
   覆盖待返回结果；任何一步失败映射 `HK_HISTORY_REFERENCE_INVALID` 且异常图为空；
4. 新增 raw drift、metadata drift、raw ABA、metadata ABA 四个直接回归；Windows 与 POSIX 均执行。测试应在
   verifier 内原地改写，以确保不是 path replacement 的重复用例；
5. 保留 original/private same-object same-number reopen、symlink/reparse/hardlink、hostile verifier、verify
   失败 finalize=0，以及 partial/no-clobber 的既有回归。

通过条件：上述四类内容漂移/ABA 全部稳定拒绝；normal v3 success 仍只读每个输入一次交给 verifier，并只传
exact bundle 给 finalize；Windows/WSL base 定向 pytest、Ruff、mypy、冷导入与 `git diff --check` 全绿。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`：

- `pytest tests/unit/test_backfill_hk_history.py tests/unit/test_hk_history_backfill.py -q`：
  `121 passed, 2 skipped`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- audit-hook 冷导入：`WINDOWS_COLD_IMPORT_NO_NETWORK_PASS`；
- 独立内容漂移/ABA：四例均错误逃逸；
- 独立 original/private same-number handle reopen：两例均正确拒绝。

WSL Miniforge base，同一 `/mnt/f` worktree：

- 对应定向 pytest：`123 passed`；
- 对应 Ruff、mypy：PASS；
- audit-hook 冷导入：`WSL_COLD_IMPORT_NO_NETWORK_PASS`；
- 独立 raw drift 与 metadata ABA：两例均错误逃逸；
- `stat -f -c %T`：`wslfs`，仅为 WSL/DrvFS 开发合同证据，**不是 ext4 Gate**。

共同检查：`git diff --check` PASS，仅有既有 LF/CRLF 提示。pytest 大量 warning 为 Pandera deprecation 与
worktree `.pytest_cache` 权限提示，不改变本轮阻断结论。

## 5. 最终状态

V3M-P0 暂不进入主 Agent 最终通过。应先按 §3 最小返工并由另一全新独立上下文复验；在修复前，不解锁
02983 provenance materialize、01065 source-freeze/verifier 或 formal V3M-P1。
