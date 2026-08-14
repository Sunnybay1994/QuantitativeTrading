# M1-HK60-V3M-P0 R2 held open-instance 内容稳定性返工交付报告

日期：2026-08-09  
结论：**R2 实现与自测 PASS，待全新独立复验和主 Agent 最终验收**

## 1. R1 现象与根因

R1 只在 verifier 后复验 retained raw/metadata 的 directory namespace、file physical identity 与
original/private descriptor open-instance continuity。同一普通文件被原地改写时 inode/file-id 不变，因此
verifier 返回时仍保留的内容漂移可以逃逸。

最初 §11 还要求只靠 held-instance 最终复读拒绝“改写后已恢复 exact original bytes”的真 ABA。实现前停止探针
证明该要求不可观测：held handle 复读的 length/SHA 与初值相同，offset 可恢复，file identity/open instance 也未
改变。任务合同随后重冻：R2 证明返回时内容与 verifier 输入 exact 相同；不声称证明窗口内从未发生瞬时写入。

## 2. 最小返工

- initial anchored read 后分别冻结 raw/metadata 的 exact length 与 SHA-256；传给 HKEX verifier 的 payload 仍各只
  initial read 一次。
- verifier 返回后，先执行 PRE-B R4 的 original/private live 与 same-open-instance 检查，再从仍持有的同一个
  file handle/fd 从 offset 0 复读到 EOF，核对 length 与 SHA-256。
- POSIX 使用 held fd 的 `lseek/read`；Windows 使用 held handle 的 `SetFilePointerEx/ReadFile`。两平台均保存原
  file pointer，并在 `finally` 精确恢复；seek/read/restore 任一步失败均覆盖待返回 result。
- 内容复核后继续执行 live/open-instance、namespace 与 path physical identity 复核。没有 path reopen 读取，
  没有 mtime/ctime、size/file-id 降级，没有文件锁、事件日志或写入世代。
- 所有失败在退出 active exception 后统一重建为 `HK_HISTORY_REFERENCE_INVALID from None`；payload、digest、
  descriptor、offset 均不进入 capability、receipt、stdout 或异常文本。

未修改 CLI 合同、HKEX parser/schema、finalize、storage、connector、legacy receipt 或正式数据路径。

## 3. 新增回归

- raw 与 metadata 各自发生 same-inode/file-id 原地 drift，并把新 bytes 保留到 verifier 返回：两平台均拒绝；
- raw 与 metadata 真 ABA 对照：临时改写后在 verifier 返回前恢复 exact original bytes，允许成功，并逐项断言
  verifier 输入、返回 bundle retained bytes 与最终路径 bytes 全部 exact 相同；
- held current-offset、seek-start、read-all、restore-offset 分别抛 ValueError/RuntimeError：固定公开码，
  cause/context/traceback 无 hostile marker；
- normal raw/metadata 复读前后 offset exact 相同；POSIX original/private 仍共享同一 OFD，Windows
  `CompareObjectHandles` 仍证明同一 kernel object；
- CLI hostile loader 继续断言 connector/finalize 调用数为零。

既有 same-number reopen、path replacement、hardlink、symlink/reparse、hostile verifier、partial/no-clobber、
legacy v2 与公开 CLI 回归全部保留。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`：

- 两个白名单测试文件：`130 passed, 2 skipped`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- cold-import audit：`WINDOWS_R2_COLD_IMPORT_NO_NETWORK_PASS`。

WSL Miniforge `base`，同一 `/mnt/f` 工作树：

- 两个白名单测试文件：`132 passed`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- cold-import audit：`WSL_R2_COLD_IMPORT_NO_NETWORK_PASS`；
- 文件系统类型：`wslfs`，属于 WSL/DrvFS 开发证据，不是 WSL2/ext4 Gate。

`git diff --check` PASS。pytest warning 仍为既有 Pandera deprecation 与工作树 `.pytest_cache` 权限提示。

## 5. 隔离、信任边界与后续状态

所有 R2 测试只使用 pytest 系统临时目录，未读取或写入正式 HK60 plan、journal、raw、clean、`data/legacy` 或
正式 artifacts；未发起网络/HKEX/Tushare/BaoStock 请求，未 add/commit，保留全部无关脏文件。

R2 能证明 verifier 返回后的 held-instance bytes 与 initial verifier 输入一致。已恢复 exact original bytes 的真
ABA 在当前无外部事件日志/排他写合同下不可观测；其通过不等于证明窗口内无写入。若未来需要该强保证，应另立
Windows/Linux retained-input exclusivity/event-journal 合同。

本报告不解锁 02983 provenance materialize、01065 source-freeze/verifier 或 formal V3M-P1；也不表示 HK60、
HK 复权、ext4 或 M1 Gate 已完成。
