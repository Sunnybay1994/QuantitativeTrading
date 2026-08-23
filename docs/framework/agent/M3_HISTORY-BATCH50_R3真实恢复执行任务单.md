# M3 HISTORY-BATCH50 R3 真实恢复执行任务单

## 目标

从静默且闭合的 `674/3186` HISTORY 账本继续，按确定性 plan 顺序最多新增 `50` 个请求；不进入 candidate、prepare 或 publish。

## 冻结前置证据

- verified `674`、missing `2512`、partial `0`
- WSL 中无残留 `quant.research.m3.run_g1` 进程
- ordered request-id SHA-256：`93b5ff3c584fd654600c8830a3054b7d3ea50d2c7a97e0f94b0f8730c9cbbbd6`
- endpoint 分布：`adj_factor=12`、`daily=13`、`dividend=11`、`stk_limit=11`、`suspend_d=3`
- 首个 identity：`38ea117fd6eadc3e906a178ef26bea13e48372805c906cac2cbeb099265d3cd8`（`suspend_d/601799.SH`）
- 末个 identity：`3d883b2cd30b623c8f767a5a9d5c08f74ddac013500a3d7efc9b132a82f4a1dc`（`adj_factor/000975.SZ`）

## 唯一执行命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 50
```

## 约束与失败语义

- 使用用户持续授权的 Tushare API；保持单写者、`60/min`、`max_attempts=5`，不输出 token。
- 承载层等待窗口覆盖真实重试窗口。若承载层 timeout/断开，先检查 WSL 子进程与写锁：原写者存活时只等待，不下发第二个写者，也不把瞬时 partial 当终态。
- 项目命令非零退出且已确认写者静默后，才执行零网络全量审计；不补跑批次余额。
- 成功条件：新增提交 `50`，静默态 verified `724`、missing `2462`、partial `0`，且仍为 `[INDEX]/INCOMPLETE`。

