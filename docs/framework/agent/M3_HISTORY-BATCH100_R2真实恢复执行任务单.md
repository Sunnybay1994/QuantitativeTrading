# M3 HISTORY-BATCH100 R2 真实恢复执行任务单

## 目标

在已验证 `573/3186` 个 HISTORY identity、`0` partial 的闭合账本上，按确定性 plan 顺序最多新增 `100` 个请求；不扩大到候选构建、prepare 或 publish。

## 冻结前置证据

- history 总数：`3186`
- 已验证：`573`
- 缺失：`2613`
- partial：`0`
- 下一批 identity 数：`100`
- endpoint 分布：`adj_factor=24`、`daily=18`、`dividend=15`、`stk_limit=23`、`suspend_d=20`
- ordered request-id 列表 SHA-256：`9d0287a94d18527d27eb97a7c3ebbf4ae9ee6db0f233df05082c5f85fa28c297`
- 首个 identity：`31dc3cf30a06747f0eaee94dd1bf3d2d32fb02f724a113fe5499828954ef1f31`（`stk_limit/300017.SZ/20151009..20260710`）
- 末个 identity：`38de2304a90c56e47acdd62421f87e8bb028ef03c23eb737828b2a8518ab998a`（`suspend_d/000712.SZ/20151009..20260710`）

## 唯一执行命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 100
```

## 边界与失败语义

- 使用用户持续授权的 Tushare 2000 积分档 API；不读取或输出 token。
- 保持配置中的单写者、`60/min`、`max_attempts=5` 和 canonical journal/raw/receipt 契约，不提高速率、不绕过等待。
- 命令只执行一次。若非零退出，立即停止；不以第二条批命令补跑未完成余额。
- 失败后只做零网络 `status` 与全量生产收据审计，区分已提交、缺失和 partial。
- 不调用候选构建、prepare、publish；预期命令成功后仍为 `[INDEX]/INCOMPLETE`。

## 通过条件

- 成功路径：退出码 `0`，新增提交恰为 `100`，全量生产验证达到 `673/3186`，缺失 `2513`，partial `0`。
- 失败路径：精确记录已提交前缀与 partial，所有已存在 receipt 仍通过生产验证，且停止继续消耗 API。

