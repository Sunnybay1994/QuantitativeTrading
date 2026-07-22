# M3 G1 B2A 请求计划与 Journal 独立六次复验报告

日期：2026-07-13  
六次返工：[`M3_G1_B2A请求计划与Journal六次返工交付报告.md`](M3_G1_B2A请求计划与Journal六次返工交付报告.md)  
前次独立复验：[`M3_G1_B2A请求计划与Journal独立五次复验报告.md`](M3_G1_B2A请求计划与Journal独立五次复验报告.md)

## 1. 身份、范围与结论

本报告由未参与实现和六次返工的独立验收 Agent 编写。本轮只读检查生产代码，使用系统临时目录运行隔离
反例；未联网、未读取 Tushare token、未访问 `_old/`，也未修改生产代码或测试。唯一项目写入是本报告。

**结论：独立六次复验通过，进入主 Agent 最终验收。** 六次返工已关闭独立五次复验记录的 snapshot/frame
混配 P1；三类原红灯、rows/columns/content 对照、bundle 内部不一致、前五轮状态漂移、静态非法状态和历史
回归均通过。源码结构也已收敛到唯一 verified read bundle，没有残留的 candidate/receipt path 二读。

截至本轮，前六轮独立验收记录的全部 P1/P2 均已关闭。本结论只表示本任务包满足进入主验的前置条件；
仍须主 Agent 复核 SSOT、跨模块不变量、全量产物和未公开反例。**不代表 B2A、B2、G1 或 M3 Gate 已通过。**

## 2. `verify_request_bundle` 同源证据验证

### 2.1 生产结构

`RawStore.verify_request_bundle` 在 `src/quant/data/storage.py:259`–`:330` 内完成：

1. 严格检查 request raw 布局；
2. data bytes 和 metadata bytes 各读取一次；
3. 严格解析 metadata 和请求身份；
4. 由捕获的 data bytes 计算 checksum/size；
5. 直接从同一 data bytes 的 `BytesIO` 解析 Parquet；
6. 比较 metadata rows/columns 与解析 frame；
7. 由捕获的两份 bytes 构造 snapshot，并与该 frame 一并返回。

冻结边界止于 bundle 完整验证返回；本轮不要求返回后的纳秒级恶意替换，也不要求跨 raw/journal 的通用
文件系统事务。

### 2.2 独立单次读取证明

独立探针对合法 request 包装 `Path.read_bytes` 计数，结果为：

```text
data.parquet read_bytes = 1
metadata.json read_bytes = 1
```

并从探针捕获的原始 bytes 独立复算：

- snapshot data checksum 等于捕获 data bytes 的 SHA-256；
- snapshot metadata hash 等于捕获 metadata bytes 的 SHA-256；
- size、rows、columns 与捕获 data bytes 解析出的 frame 一致；
- bundle frame 与同一 data bytes 的内存解析结果全等；
- bundle snapshot 与 `write_request` 返回值、兼容 `verify_request` 返回值全等。

因此 snapshot 和 frame 确由同一组捕获证据派生，而不是两次路径读取的拼接。

### 2.3 Bundle 内部边界变体

独立新增 11 个 bundle 内部变体，结果 **11/11 拒绝**：

| 变体 | 结果 |
|---|---|
| data bytes 改变但 metadata 未更新 | hash/size 拒绝 |
| metadata checksum 错误 | hash/size 拒绝 |
| metadata size 错误 | hash/size 拒绝 |
| metadata rows 错误 | frame/metadata 行列拒绝 |
| metadata columns 错误 | frame/metadata 行列拒绝 |
| metadata 缺字段 | 字段集合拒绝 |
| metadata duplicate key | 严格 JSON 拒绝 |
| metadata 非 UTF-8 | 严格 JSON 拒绝 |
| 非法 Parquet，且 hash/size 已同步 | Parquet 解析拒绝 |
| `fetched_at` 缺时区 | 时间语义拒绝 |
| rows 使用 bool 冒充 int | 精确类型拒绝 |

该集合覆盖并超过“至少 5 个 bundle 内边界变体”的要求，且明确覆盖 metadata、hash、size、rows、columns。

## 3. M3 verifier 源码二读审计

对 `src/quant/data/m3_backfill.py` 做精确文本和调用位置检查：

| 禁止项 | 命中数 |
|---|---:|
| `verify_request(` | 0 |
| `_read_parquet_sanitized` | 0 |
| `pl.read_parquet` | 0 |
| `snapshot.data_path.read/open/read_bytes` | 0 |

`verify_request_bundle(` 恰有 3 个调用者：

- `verify_tushare_receipt`；
- candidate recovery/build；
- `_verify_candidate`。

另外两个 `snapshot.data_path` 文本仅用于 receipt path 等值比较和生成受控相对路径，没有读取文件。candidate
和 receipt verifier 均直接消费 bundle 返回的 snapshot/frame，不存在 snapshot path 二读。

## 4. Commit 前六变体与原红灯

在最终 commit 前第二次 bundle 调用开始前注入 raw 变化。六项均确认注入实际发生，connector、monotonic、
sleep 均为 `0/0/0`，candidate/receipt 均无当前执行器新增或覆盖：

| 变体 | 稳定结果 | Journal 副作用 |
|---|---|---|
| metadata-only identity 改变 | `CANDIDATE_RAW_EVIDENCE_MISMATCH` | 0 |
| 同逻辑内容、不同物理 Parquet bytes | `CANDIDATE_RAW_EVIDENCE_MISMATCH` | 0 |
| metadata checksum/hash 错误 | `CANDIDATE_RAW_INVALID` | 0 |
| rows 改变 | `CANDIDATE_RAW_EVIDENCE_MISMATCH` | 0 |
| columns 改变 | `TUSHARE_RESPONSE_COLUMNS_INVALID` | 0 |
| logical content 改变，即 COMPLETE-A → COMPLETE-B | `CANDIDATE_RAW_EVIDENCE_MISMATCH` | 0 |

独立五次复验的三类混配红灯已全部转绿；rows/columns/content 三项对照也保持 commit 前拒绝。

## 5. 前五轮状态与历史回归

### 5.1 candidate 与 expected mode

| 组合 | 结果 | 当前执行器副作用 |
|---|---|---|
| candidate false → true | closure changed | 外部 candidate bytes 原样保留，无 receipt |
| candidate true → false | closure changed | 不重建被移除 candidate，无 receipt |
| expected NETWORK → COMPLETE | closure changed | 保留 intent，无 candidate/receipt |
| expected RECOVER → ABSENT | closure changed | 无 candidate/receipt |

四项 connector/monotonic/sleep 均为 `0/0/0`。

### 5.2 静态非法 14 与 preflight 20

- 静态非法状态：**14/14 通过**。九种非法 raw 布局、COMPLETE 缺 intent、candidate 缺 intent、
  candidate+raw ABSENT/EMPTY、损坏 intent，全部在 `0/0/0` 时失败，raw/journal 普通文件路径和 bytes 零
  增量、零覆盖。
- `_NoReceiptPreflight` 非法 type/enum/cross-field：**20/20 拒绝**；四个冻结合法组合：**4/4 通过**。

### 5.3 兼容 API、IO 脱敏和 public dataclass

- `verify_request(...) -> RequestRawSnapshot` 签名和返回语义不变，返回值与 bundle snapshot 相同；
- legacy `RawStore.write` 相同输入/时间戳继续幂等，data/metadata 文件存在；
- 定向套件继续覆盖 forged public request/batch、嵌套构造后篡改的 pre-IO 拒绝；
- mkdir/open/close/link/fsync/lock cleanup、Parquet、provider/classifier 错误保持稳定脱敏；
- journal 非普通项、symlink、FIFO 和不覆盖语义未回归。

## 6. 工具链结果

全部命令在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
135 passed in 7.72s

python -m pytest -q
436 passed, 1179 warnings in 14.27s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 是已有 Pandera/Polars deprecation warning。真实网络、token 和真实 Tushare 配额不在本轮
范围内。

## 7. 独立复验状态

本轮在冻结威胁边界内未发现新 finding，前六轮记录的全部 P1/P2 已关闭，独立六次复验通过。所有隔离探针
使用系统 `TemporaryDirectory` 并已退出清理；项目目录排除 `_old/` 后复查 `.tmp/.temp/.writer.lock`、探针
payload、candidate/receipt 临时证据，残留为 **0**。

下一步必须由主 Agent 执行最终契约、真实依赖、全量回归、SSOT 和跨模块一致性验收。只有主验实际通过后
才能更新对应任务状态；本报告本身不授权更新路线图、B2A、B2、G1 或 M3 Gate。
