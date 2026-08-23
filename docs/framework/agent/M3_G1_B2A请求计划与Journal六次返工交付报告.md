# M3 G1 B2A 请求计划与 Journal 六次返工交付报告

日期：2026-07-13  
独立五次复验：[`M3_G1_B2A请求计划与Journal独立五次复验报告.md`](M3_G1_B2A请求计划与Journal独立五次复验报告.md)  
五次返工：[`M3_G1_B2A请求计划与Journal五次返工交付报告.md`](M3_G1_B2A请求计划与Journal五次返工交付报告.md)  
状态：已完成 snapshot/frame 混配 P1 结构性最小返工并自测；等待独立六次复验，不代表 B2A/B2/G1/M3 通过

## 1. 范围与红灯证据

本轮只修改 `src/quant/data/storage.py`、`src/quant/data/m3_backfill.py`、对应两个单元测试文件，并新增本报告。
未修改独立报告、SSOT、路线图、Gate 或其他任务包；未联网、未读取 token 或 `_old/`。独立五次复验确认
前次 COMPLETE-A→B 和 candidate existence 双向漂移已经关闭，本轮只处理新的 snapshot/frame 混配 P1。

先加入最终 verifier 的 6 个变体。旧实现结果为 **3 失败、3 通过**：

- metadata-only 合法变化、同逻辑不同物理 Parquet bytes、错误 metadata checksum 三项都会新增 candidate 和
  receipt，之后才由 receipt verifier 报错；
- rows、columns、logical content 改变三项能在旧 candidate 比较或字段门禁处于 commit 前拒绝。

所有重试 connector、monotonic、sleep 为 `0/0/0`。三个红灯与独立五次复验一致。

## 2. 为什么两次成功读取不能组成一次 verified identity

旧流程先由 `verify_request` 读取 data/metadata bytes，验证物理 hash、metadata hash、size、rows 和 columns，
然后只返回 `RequestRawSnapshot`。调用方随后按 `snapshot.data_path` 第二次读取 Parquet，并从第二次 frame 计算
response content。

这两个动作单独成功，只分别证明：

1. 第一次读取时存在一套物理和 metadata 证据 A；
2. 第二次读取时路径上存在一个可解析 frame B。

它们没有证明 snapshot A 与 frame B 来自同一份 data bytes。metadata-only 变化不会改变第二次 frame；同一
逻辑 frame 的不同 Parquet 编码不会改变 content digest；错误 metadata checksum 也不会影响第二次直接读
data。因此把两次结果拼接，会产生一个存储中从未被整体验证过的“旧 snapshot + 当前 frame”身份。

系统不变量应是：checksum、size、rows、columns 和 frame/content 必须由同一次捕获的 data bytes 派生，
metadata hash 必须来自同一次捕获并参与该次联合校验。

## 3. 唯一 verified read bundle

`RawStore` 新增唯一绑定读取接口：

```text
verify_request_bundle(...) -> tuple[RequestRawSnapshot, pl.DataFrame]
```

接口执行一次完整读取流程：

1. 严格检查 request raw 物理布局；
2. 各读取一次 data bytes 和 metadata bytes；
3. 严格解析 metadata，并验证请求、时区、类型和字段集合；
4. 由捕获的 data bytes 计算 checksum/size，并与捕获的 metadata bytes 比较；
5. 直接从同一 data bytes 的内存缓冲解析 Parquet frame；
6. 比较 frame rows/columns 与 metadata；
7. 由同一组 bytes 构造 snapshot，并和该 frame 一起返回。

没有新增可由外部直接构造的公共 bundle dataclass。现有
`verify_request(...) -> RequestRawSnapshot` 保持签名和返回语义，内部调用 bundle 并只返回 snapshot，因此
`RawStore.write_request`、legacy 调用和既有测试保持兼容。

## 4. B2A 消费路径收敛

以下三个“snapshot + frame”消费者全部直接调用 bundle：

- candidate recovery；
- `_verify_candidate`，包括 candidate commit 前完整重验；
- `verify_tushare_receipt`。

三处均使用 bundle 返回的 snapshot 和 frame 做领域字段门禁、candidate 重建或 receipt 证据比较。已删除
`_read_parquet_sanitized`，不再取得 snapshot 后按 path 二读。

源码搜索结果：

```text
src/quant/data/m3_backfill.py:691  verify_request_bundle
src/quant/data/m3_backfill.py:824  verify_request_bundle
src/quant/data/m3_backfill.py:901  verify_request_bundle
```

`m3_backfill.py` 中 `verify_request(`、`_read_parquet_sanitized` 和 `pl.read_parquet(snapshot.data_path)` 均为 0。
`storage.py` 中的 `verify_request` 只作为兼容 API，并委托 bundle。

## 5. 新增回归

### 5.1 Commit 前六变体

最终 verifier 第二次 bundle 读取前注入 raw 变化：

| 变体 | 修复后结果 |
|---|---|
| metadata-only 合法变化 | commit 前 candidate identity 不一致，零 candidate/receipt |
| 同逻辑不同物理 Parquet bytes | commit 前物理证据不一致，零 candidate/receipt |
| metadata checksum 错误 | bundle 内 hash 校验失败，零 candidate/receipt |
| rows 改变 | candidate/领域验证失败，零 candidate/receipt |
| columns 改变 | 领域字段验证失败，零 candidate/receipt |
| logical content 改变 | candidate content digest 不一致，零 candidate/receipt |

六项均确认注入实际发生，connector/clock/sleep 为 `0/0/0`。

### 5.2 Bundle 自身

- 合法 bundle 的 snapshot 等于原写入 snapshot，frame 等于原 frame；
- 旧 `verify_request` 返回同一 snapshot；
- data checksum、data size、metadata rows、metadata columns 与捕获 bytes/frame 不一致时全部拒绝。

完整定向套件继续覆盖前五轮漂移、静态非法 14、preflight 构造、IO 脱敏、journal 不覆盖和
legacy `RawStore.write/verify_request` 行为。

## 6. 验证结果

全部命令在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py -k "never_mixes_snapshot or verified_bundle"
11 passed, 124 deselected in 1.74s

python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
135 passed in 7.34s

python -m pytest -q
436 passed, 1179 warnings in 14.50s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 是既有 Pandera/Polars deprecation warning，本轮未修改其来源。

## 7. 威胁模型边界与状态

冻结边界止于 bundle 完整验证返回：保证返回的 snapshot 和 frame 由同一组已捕获 bytes 联合验证，不继续
追逐 bundle 返回后的纳秒级外部恶意文件替换，也不宣称提供跨 raw/journal 的文件系统事务。

- 本轮实现者自测已通过；
- 未修改独立报告、路线图、Gate 或 SSOT 状态；
- 当前只能写“等待独立六次复验”；
- 独立复验通过后仍需主 Agent 最终验收，不得据此宣称 B2A、B2、G1 或 M3 通过。
