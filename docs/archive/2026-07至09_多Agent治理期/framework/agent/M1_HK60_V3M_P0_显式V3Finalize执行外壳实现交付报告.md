# M1-HK60-V3M-P0 显式 v3 finalize 执行外壳实现交付报告

日期：2026-08-09  
结论：**实现与自测 PASS，待全新独立初验和主 Agent 最终验收**

## 1. 实现范围

- `backfill_hk_history` 新增显式 `--finalize-v3` 与
  `--hkex-retained-metadata`；v3 必须同时接收 caller 提供的 raw 与 canonical metadata，且与 legacy
  finalize、recover、uncertain retry 严格互斥。
- 新增窄公共 loader `load_verified_hkex_retained_bundle_for_finalize`。它分别以 PRE-B 已验收的
  `_DirectoryAnchor` 锚住两个输入父目录，每个文件只读取一次，持有 original/private duplicate 到 fresh HKEX
  verifier 与最终 namespace/physical identity 核验结束；same-file/hardlink、symlink/reparse、非普通文件、
  replacement/ABA、descriptor/close 失败均 fail closed。
- v3 在加载 plan 前先验证 exact journal/raw/clean 三个角色根 pairwise disjoint、无祖先关系、无已有
  symlink/reparse/physical alias，且 plan 不位于任一可写角色根内。合法的共同 `data-root` 父目录不参与角色互斥。
- v3 成功只向 `finalize_hk_history` 传 exact retained bundle，不传 legacy raw-only 参数；stdout 显式包含
  `hk-history-finalize-v3`、published rows、bundle id 与 metadata identity。
- CLI 对未知或 hostile 异常只输出公开稳定码；loader/finalize 的任意非公开异常不会回显 path、raw、metadata
  或 marker。

未修改 HKEX parser/schema、domain schema、storage、connector、legacy v1/v2 receipt 或四文件事务实现；未新增
metadata、`source_observed_at`、plan、execution manifest 或正式 migration 路径。

## 2. 新增验证覆盖

- v3 raw-only、metadata-only、双缺、legacy/recover/retry 混用，以及 metadata 在非 v3 模式使用；
- exact bundle 参数传递、零 connector 构造、显式 v3 stdout identity；
- 双文件各 read-once、same-file/hardlink、symlink/reparse、path replacement 与 hostile exception graph；
- plan 位于 writable root、journal/raw/clean 角色重叠；
- 公开 CLI 的首次发布、exact retry 幂等、partial 四文件 fail closed、异 bytes 不覆盖；
- 既有 legacy raw-only/v2、四文件第二/第三/第四写失败、竞争抢占、clean preflight 与 capability 全部回归。

## 3. 验证结果

Windows 原生 `D:\Miniforge3\python.exe`：

- 两个白名单测试文件：`121 passed, 2 skipped`；两个 skip 为 Windows 不可用的 POSIX/symlink 平台用例；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- 冷启动 network audit probe：`WINDOWS_COLD_IMPORT_NO_NETWORK_PASS`。

WSL Miniforge `base`，同一 `/mnt/f` 工作树：

- 两个白名单测试文件：`123 passed`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- `stat -f -c %T` 返回 `wslfs`。这是 WSL/DrvFS 开发合同证据，不是 WSL2/ext4 Gate。

共同检查：`git diff --check` PASS。pytest warning 为既有 Pandera deprecation 与工作树 `.pytest_cache`
权限提示，不影响断言结果。

## 4. 隔离与诚实边界

所有新增测试仅使用 pytest 系统临时目录；未读取或写入正式 HK60 plan、旧
`hk60_2026-07-10` journal、正式 raw/clean、`data/legacy` 或正式 artifacts，也未发起网络/Tushare/BaoStock/HKEX
请求。工作树原有 PRE-B、P1、U0C 等脏改动和未跟踪文件均保留，未 add/commit。

本包只证明 fixture-only 显式 v3 执行外壳的工程合同；不表示 canonical 02983 observed-at provenance、licensed
01065 source freeze/verifier、正式 V3M-P1 migration、HK60、HK 复权、ext4 或 M1 Gate 已完成。
