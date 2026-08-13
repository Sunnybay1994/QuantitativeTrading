# M1-HK-CA-P1-PRE-B R2：目录锚与异常图脱敏返工交付报告

日期：2026-08-09  
角色：R2 实现 Agent  
状态：返工实现与自测完成，等待全新独立复验；不宣布 Gate

## 1. R1 FAIL 闭环

### 1.1 验证窗口 root ABA

- 现象：R1 仅比较读取前后的 path identity；`original → copy → original` 可在一次 fresh load 内读取 copy 后
  恢复原 identity，并签发 capability。
- 根因：retained/clean 文件仍用普通 path reader，没有贯穿窗口的物理目录对象，也没有 anchored descendant
  open。
- 应遵循规则：任务单 §11 要求 journal、seed、raw-store、clean 四类 root 在 rebuild 与签发全窗口保持平台
  安全锚；actual exact partition 必须相对锚打开。
- 最小复现：在四类 root 首次实际读取前 rename 原目录、复制回同一路径，并在调用结束前恢复。
- 新增测试：四类 root × public load/verify 共 8 组窗口内 ABA；Windows 验证 no-share-delete handle 阻止
  rename，或 namespace identity 漂移时 fail closed；POSIX 实际完成 rename/copy 并稳定拒绝。
- 通过条件：任一复制/替换目录不参与被验读取；namespace 漂移稳定返回冻结错误且不签 capability。

### 1.2 hostile exception graph 泄漏

- 现象：顶层错误码已脱敏，但 `__context__` 可追回 reader 的 TOKEN/path marker。
- 根因：多层在 active `except` 内包装 `raise ... from None`；这只隐藏默认展示，不清除异常对象图。
- 应遵循规则：public load/verify/HKEX retained verifier 必须离开 active exception handler 后才创建唯一公开错误。
- 最小复现：让 parquet、JSON/root reader 或 HKEX verifier 抛含 marker 的 ValueError/RuntimeError，再递归遍历
  `__cause__`/`__context__`。
- 新增测试：两种异常类型 × 四类 hostile reader × load/verify，加直接 HKEX retained verifier；同时检查
  message、repr、完整异常图与格式化 traceback。
- 通过条件：公开稳定错误的 cause/context 均为 None，递归异常图与 traceback 不含 marker。

## 2. 最小实现

- 新增窗口级 `_ReadAnchors`，同时持有 journal、seed、raw-store、clean 四个 `_DirectoryAnchor`，直到 bars、
  availability、root identity 与 HMAC attestation 全部构造完成后才关闭。
- POSIX：`O_DIRECTORY | O_NOFOLLOW` root fd；逐目录 `open(..., dir_fd=..., O_NOFOLLOW)`，最终文件从 fd
  读取并由 bytes 交给 JSON/Parquet parser。
- Windows：`CreateFileW` + `FILE_FLAG_BACKUP_SEMANTICS/OPEN_REPARSE_POINT`，share mode 只允许 read/write、
  不允许 share-delete；root、后代目录与 exact 文件均持有 handle，校验 reparse 与 file identity，再由 handle
  读取 bytes。
- 每次 anchored read 前后及 capability 签发前后核对 namespace→anchor identity，关闭 path ABA；actual seed、
  no-trade evidence、request raw/metadata/receipt、HKEX 四文件与 clean exact date partitions 全部改走锚定 reader。
- public load/verify 与 HKEX retained/raw verifier 捕获后仅保存冻结错误码，离开 active `except` 后重新创建并
  `raise ... from None`；close failure 同样在 public 边界统一映射。
- v3 schema、availability retained-observation 语义、四文件格式、legacy v1/v2 与 no-clobber 实现未改变。

## 3. 验证

Windows Miniforge：

- Ruff：通过；
- mypy：4 个 source 文件通过；
- pytest：`134 passed, 1 skipped`。skip 是既有 official retained raw 条件。

WSL Miniforge base（`/mnt/f` DrvFS）：

- Ruff：通过；
- mypy：4 个 source 文件通过；
- pytest：`135 passed`；
- POSIX ABA/exception graph 聚焦：`15 passed`。

DrvFS 结果不表示 ext4/Linux Gate。

## 4. 边界

- 仅修改 PRE-B 原白名单生产/测试文件并新增本报告；没有网络、正式 02983/01065 data/journal、add 或 commit。
- 既有 worktree 脏文件全部保留。
- 本轮仍是开发 capability 返工；正式 v3 migration、HK60、ext4 与 M1 Gate 均未关闭。
