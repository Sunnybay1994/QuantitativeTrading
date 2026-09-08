# M3 G2C Provider 公共 API 验真交付报告

日期：2026-08-02
分支：`codex/m3-g2a`
状态：**正式 G2C 定向合同通过；正式产物证据见下文；未关闭 Linux/ext4 Gate，未启动 G3A**

## 1. 范围与冻结设计

- 只消费已 fresh verify 的正式 G2A snapshot 与 G2B provider，不重启或修改正式 G1，不改写既有 G2A/G2B 字节和收据。
- parent 不 import Qlib；每次验真以参数数组启动全新 Python，worker 只对唯一 provider URI 执行一次 `qlib.init`。
- sample 按冻结 hash 策略选择 SH/SZ 分层的 3 个证券，每个精确 20 个 emitted date，七字段合计固定 420 cells；另对首尾期间最多 15 个 gap keys 逐 cell 对账。
- worker 只写 raw rows 与 API 摘要；parent 重算 expected float32 bits、missing/extra/duplicate/non-finite/mismatch/gap、calendar/instrument 差异和所有 digest。
- 产物目录只包含 `provider_validation.parquet` 和 `provider_validation.json`；重试目标必须预先不存在，写入使用 exclusive create。
- 正式输出仅位于 `artifacts/formal_g2c_wsl/release=<release_id>/`。运行是 WSL py312，但输入/输出均在 `/mnt/f` DrvFS，不等价于 Linux/ext4 Gate。
- 为满足下游 receipt 精确路径闭包，在 G2B 根内新增了与原 `provider-receipt.json`
  字节相同的 `receipts/provider/<provider_key>.json` canonical mapping；原 G2B provider 和原收据均未改写。

## 2. 实现与反例

- 新增 formal/development 类型隔离的 probe、validation summary/result 与 verified artifact 合同。
- 新增 parent `provider_validation` 与独立 `qlib_adapter` worker；package `__init__` 只导出 parent API，不 import worker。
- 覆盖确定性与 hash tie、缺市场/不足 20 rows、fresh worker 隔离、identity echo、MultiIndex/时区/非零点、missing/extra/duplicate，字段顺序、signed-zero/NaN/Inf、gap absent/NaN/finite、calendar/instrument 漂移、timeout/非零/坏 JSON/Parquet、parent 预加载 Qlib、输入树漂移和 summary 整套伪造重算失败。

## 3. 正式执行证据

```text
G1 fresh verify: PASS
G2A fresh verify: PASS
G2B fresh verify: PASS
G2C fresh-process public API + disk re-verification: PASS
provider_validation_key=65bda5759316a1514bc4a8546ec4f2e70a0830ffbfc521bf7fca25cd88e3475e
summary_sha256=fa9eab7e79af182eee18a4d486628dbe7b43ea8b0a18014411ab5a02be128b74
validation_receipt_sha256=affd75508288548b83420251788e81a3fabc179c47f9209b09cffec73808acfc
probe_plan_sha256=6a2b7c20112976b2d8e8363e75dd2630dc2f65e056db100455d63112161a6ce8
details_sha256=716f7840bf6fd33311daf93bfde7e5cbfd662c4c9ca5f04e4e167c0312eba6bf
api_calendar_sha256=3569ee429fa02cdb0e1faf41430678bf7b9cafc736aa907b4fffd458a940799b
api_instrument_ranges_sha256=c3b3ef7c1842ce4aa0330ae0f5dc7a3e56f036b85fc0dbbb88c893967b98b4fa
elapsed_seconds=1468.292
```

抽样证券为 `000100.SZ`、`600104.SH`、`601336.SH`。实际对账为 60 emitted keys / 420 cells
和 5 gap keys / 35 cells，共 455 行 details；状态为 420 `MATCHED` + 35 `GAP_NAN`，八个错误/漂移计数均为 0。
receipt 精确包含 5,024 个 inputs 和 2 个 outputs；details、summary、receipt 分别为 10,189、2,098、937,358 bytes。

## 4. 定向验证

```text
Windows Miniforge pytest: 67 passed, 4 skipped
Windows Miniforge targeted Ruff: PASS
Windows Miniforge targeted mypy: PASS
WSL Miniforge base pytest: 69 passed, 2 skipped
WSL Miniforge base targeted Ruff: PASS
WSL Miniforge base targeted mypy: PASS
WSL py312 / pyqlib 0.9.7 formal public API validation: PASS
git diff --check: PASS
```

Windows 的 skipped 包含平台不支持的 symlink/hardlink 路径反例与显式 real-Qlib 测试；WSL base 未安装 Qlib，真实公共 API 验真固定在 py312 执行。

## 5. 边界与后续

- 本次结论是正式 G2C 在 WSL py312 + DrvFS 上的开发/合同验真；Linux/ext4 不可变发布 Gate 仍待对应平台终验。
- G3A 未在本任务中启动。
