# M3 G2B Provider 构建与静态验真交付报告

日期：2026-08-02
分支：`codex/m3-g2a`
实现基线：`969d9bd`
状态：**正式 G1/G2A 输入上的 WSL py312 + Qlib 0.9.7 DrvFS 执行通过；未关闭 Linux/ext4 Gate，未启动 G2C**

## 1. 范围与身份边界

- 只消费正式 G1 release `08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`
  及已验真的正式 G2A snapshot；未修改 G1 release、journal、raw 或既有 G2A bytes/receipt。
- provider parent 不 import Qlib；唯一真实 argv 使用固定 `dump_all`、七字段、`day`、单 worker。
- formal API 只接受精确 `VerifiedSnapshotArtifact`；development example 类型仍由独立入口和稳定错误域隔离。
- 运行在 WSL py312，但输入与输出位于 `/mnt/f` DrvFS；本报告不把结果表述为 Linux/ext4 Gate。

## 2. 发现并关闭的执行前漂移

本 worktree 的 tracked `data/external/qlib/v0.9.7/dump_bin.py` 曾为 22,389 bytes、SHA-256
`f92d124048ecda23862c7e67b747c26d5e61ad21bbbe17c5304744d627b99533`，与配置冻结的 21,847 bytes、
`b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f` 冲突。preflight 在 subprocess 前
fail-closed；现已恢复冻结 bytes，并新增回归测试直接绑定仓库文件与 narrow config。

另有两次稳定 preflight 拒绝：conda `bin/python` 是 symlink，以及 `/home/mabw/AI_Coding_win` 是指向
`/mnt/f/AI_Coding` 的 symlink。执行端改传同一解释器的 resolved 普通文件与同一工具的 canonical `/mnt/f`
路径；未放宽生产 symlink/reparse 防护。独立 `_validate_preflight` 返回 `PREFLIGHT_PASS` 后才启动真实 dump。

## 3. 正式执行证据

运行环境：Python 3.12.13，pyqlib 0.9.7，numpy 2.2.6，pandas 2.3.2，pyarrow 20.0.0，fire 0.7.1，
tqdm 4.68.4，loguru 0.7.3。

```text
G1 fresh verify: PASS
G2A fresh verify: PASS
G2B_FORMAL_WSL_DRVFS_VERIFY_PASS
provider_key=b6ecc2718bc2899d35d14c1263ec9a2f70c71dfbdc8642dafae21cc39a65c17f
provider_manifest_sha256=2f4f457d12e1ce6abc0537a2daee4357a2fd6099c6f541207e4ad3ff173c8de7
provider_receipt_sha256=2a28307e8bb16d1758c3bc077e9ca8a22fa356c153222717897e20dd53ddb35b
runtime_sha256=43d70d7e344ceef10de148135dd8c9d146a5c1bf70d8deb726bbf46cf4bdcdbc
calendar_count=2614
instrument_count=627
provider_file_count=4391
output_bytes=43702295
elapsed_seconds=1358.317
```

provider receipt 为 `stage=provider / scope=PROVIDER`，精确包含 632 个 inputs 和 4,392 个 outputs；tree、
calendar、instrument range 摘要分别为：

```text
output_tree_sha256=7e249385a03ba40237bb824f110877b40ff7345b1abf374c4080a7233a6bd72a
calendar_sha256=b1984fe9c5f315b7593ea29940f8fb32bc5eec8cb925eea1fba213995b96c045
instrument_ranges_sha256=c3b3ef7c1842ce4aa0330ae0f5dc7a3e56f036b85fc0dbbb88c893967b98b4fa
```

隔离产物位于 `artifacts/formal_g2b_wsl/release=08eb9b31...7359/`；运行脚本和诊断脚本位于相邻 ignored
artifacts 目录，仅用于重现本机执行，不进入生产 import 路径。

## 4. 定向验证

```text
Windows Miniforge: fetch tool + provider materialization = 20 passed, 2 skipped
WSL Miniforge base: fetch tool + provider materialization = 21 passed, 1 skipped
Windows Miniforge: targeted Ruff = PASS; targeted mypy = PASS
WSL Miniforge base: targeted Ruff = PASS; targeted mypy = PASS
WSL py312: real Qlib 0.9.7 full provider materialization/static verification = PASS
```

上述定向 pytest、Ruff 与 mypy 均已完成；提交前另执行 `git diff --check`。G2C public API
fresh-process sample 尚未启动；Linux/ext4 不可变发布与平台 Gate 仍待独立终验。
