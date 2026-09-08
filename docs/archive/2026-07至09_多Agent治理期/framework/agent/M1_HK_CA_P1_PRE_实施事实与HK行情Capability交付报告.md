# M1-HK-CA-P1-PRE：实施事实与 HK 行情 Capability 交付报告

日期：2026-08-09  
状态：**实施事实 capability 已交付，待独立初验；HK bar capability 按停止条件未实施**  
边界：来源无关开发合同，不是正式 HK 数据、HK60、复权、M1 或 ext4 Gate

## 1. 交付结果

本轮完成了可与 P0 fresh 结果闭包的 `VerifiedImplementedHkCorporateActionSet`：

- 新增严格 `HkCorporateActionImplementationEvidenceSchema`，只接受 `IMPLEMENTED`，绑定 P0 actions、
  revision evidence、query 三份摘要以及 retained raw/metadata/bundle 和逐行 canonical digest；
- 新增实施事实 query、capability、显式 retained raw file/bundle、source adapter Protocol、parsed-only factory；
- `verify_hk_corporate_action_implementation_source` 先 fresh 调用 P0 result verifier，再验证 capability、retained
  bytes、exact event set、source/revision identity 和 evidence digest，只有该入口签发 content-bound process-local
  HMAC attestation；
- selector 与 public verifier 每次 fresh 重验 P0、raw bytes、projection、exact actions/evidence 一一映射和
  attestation；factory-only、pickle、旧 token、whole-rehash、缺失 event、future confirmation、PENDING 和跨
  symbol/type/event/revision 均 fail closed；
- hostile adapter 异常在 active `except` 外重建，公开 code 稳定，cause/context 为空且 traceback 不含 marker。

未计算 total-return，未决定现金再投资日、同日事件顺序、FX、RIGHTS、税费或归一化锚点。

## 2. HK bar capability 停止证据

任务书第 11 节停止条件已触发，本轮没有新增 `VerifiedHkBarBundle`、availability schema 或 history loader，也没有
修改 `hk_history_backfill.py`：

1. seed metadata 的 `fetched_at` 与 seed raw/metadata hash 已被 plan 绑定，可保守解释为该 retained seed 的
   observation time；
2. Tushare request metadata 的 `fetched_at` 可由 `RawStore.verify_request_bundle` fresh 验证，request receipt 也
   绑定 request id、raw/metadata digest、row count 和 request clean digest，可保守解释为对应 retained request
   的 observation time；
3. 但是当前 `finalize.json` 只有 plan、row count、全体 clean digest（及可选 supplement 摘要），没有 canonical
   的逐 `(symbol, trade_date)` 到 seed/request/availability evidence 投影；下游自行按 symbol/plan 分区重建会形成
   第二套未冻结映射合同；
4. HKEX `02983.HK` supplement 的 verifier/receipt 只有 source record、raw/evidence/content identity，没有
   canonical metadata、`observed_at` 或 `fetched_at`。因此即便 Tushare/seed 部分可重验，也不能对 exact v2
   effective keys 统一证明每行 `bar_available_at`；
5. 用 `trade_date < as_of.date()`、文件 mtime、当前时间或调用方 DataFrame 填 availability 都违反冻结合同。

后续应由独立任务冻结并发布带逐 key retained-source projection 的 receipt 版本，同时为 HKEX supplement 增加
canonical metadata/observed-at 闭包；在此之前稳定状态是 `HK_BAR_CAPABILITY_UNSUPPORTED`，不签发 capability。

## 3. 修改范围

- `src/quant/domain/schemas.py`：实施事实 schema；
- `src/quant/domain/__init__.py`：schema 公共导出；
- `src/quant/data/hk_corporate_action_implementation.py`：来源无关实施事实 capability；
- `tests/unit/test_schemas.py`：schema 合法/非法边界；
- `tests/unit/test_hk_corporate_action_implementation.py`：source wrapper、exact scope、fresh verifier、attestation、
  whole-rehash 和异常脱敏测试；
- 本报告。

没有修改 connector、history、HK60/U0C/G1、正式 data/artifacts/journal、`data/legacy`、依赖或 enums；没有联网、
读取凭据、add 或 commit。worktree 其他既有脏文件与临时目录均保留，不认领、不清理。

## 4. 验证结果

Windows 原生 Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py \
  tests/unit/test_hk_corporate_action_implementation.py \
  tests/unit/test_hk_history_backfill.py \
  -q -p no:cacheprovider --basetemp %TEMP%\hk-ca-p1-pre-full-win
94 passed, 1 skipped in 20.93s

D:\Miniforge3\python.exe -m ruff check <改动生产与测试文件>
All checks passed!

D:\Miniforge3\python.exe -m mypy \
  src/quant/domain/schemas.py src/quant/domain/__init__.py \
  src/quant/data/hk_corporate_action_implementation.py
Success: no issues found in 3 source files
```

首次使用 worktree 内相对 `--basetemp` 时，前两组测试通过后其父目录被测试生命周期移除，导致 history 的 22 个
`tmp_path` setup error；改用系统临时目录绝对路径后同一三文件集合通过，未出现断言失败。

WSL Miniforge `base`，同一 `/mnt/f` worktree：

```text
PYTHONPATH=src python -m pytest <同一三文件集合> \
  -q -p no:cacheprovider --basetemp /tmp/hk-ca-p1-pre-wsl
95 passed in 18.66s

ruff check <同一改动生产与测试文件>
All checks passed!

mypy <同一改动生产文件>
Success: no issues found in 3 source files
```

WSL 路径是 DrvFS，不是 ext4；上述结果只证明双平台开发合同反馈。

## 5. 标准到证据

| 冻结标准 | 代码 / 测试证据 |
|---|---|
| P0 必须 fresh 验证 | source wrapper、selector、public verifier 均调用 P0 public verifier；P0 result drift 测试 |
| exact canonical event scope | query 排序唯一 ids；frame ids exact equality；actions 的 symbol/type/source/event/revision 一一比对 |
| 只接受来源确认实施 | schema 与 Python 边界都只接受 `IMPLEMENTED`；PENDING、future confirmation 测试 |
| retained/content whole-rehash fail closed | 逐 file fresh SHA、bundle/projection/row digest、HMAC；raw drift 与 whole-rehash 旧 token 测试 |
| 调用方不能自报 capability | factory 只产 parsed-only；consumer 拒绝 factory-only；projection/set 不可 pickle |
| 稳定脱敏异常 | hostile adapter active RuntimeError 测试验证 code、cause/context 与 traceback |
| bar availability 不猜测 | 未增加 loader/schema；本报告逐项记录 receipt/finalize/HKEX 缺口 |

## 6. 剩余边界

- 本交付等待未参与实现的新上下文独立初验；实现者不宣布开发合同或 Gate 通过。
- 实施事实 capability 只证明未来 source adapter 对显式 retained bytes 所投影的事实；本轮没有真实 licensed
  HK source adapter 或真实 implementation status 数据。
- HK bar capability、gross total-return 公式/fixture、真实 HK 数据性能、HK60、M1 与 ext4 仍未关闭。
