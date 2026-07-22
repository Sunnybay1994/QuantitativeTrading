# M3 HISTORY-BATCH25 R4 真实恢复执行任务单

## 目标与冻结集合

从 verified `677`、missing `2509`、partial `0` 的静默账本继续，最多新增确定性 plan 的下 `25` 个 identity。

- ordered request-id SHA-256：`275a13df7cd662f4e9dab7f7a31b3c388ab9b3ef7bbff6d183e233ea3703b204`
- endpoint 分布：`adj_factor=6`、`daily=9`、`dividend=6`、`stk_limit=3`、`suspend_d=1`
- 首个：`393592cb1cd60ab5923b333d13fb76ebb60b6d0d47e98a2131afc24bc7918bce`（`dividend/002271.SZ`）
- 末个：`3b1cefb69e19226f59431401c0ea418c90ca6ea30ed04c69d5b97b2d376f558b`（`daily/002027.SZ`）

## 唯一命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 25
```

## 约束与通过条件

- 用户已持续授权 Tushare API；保持单写者、`60/min`、`max_attempts=5`，不输出 token。
- 承载层异常时先确认 WSL 子进程/写锁静默；存活时只等待。
- 项目失败且写者静默后只审计，不补跑余额；仅可另行冻结唯一 partial 恢复。
- 成功条件：新增 `25`、verified `702`、missing `2484`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

