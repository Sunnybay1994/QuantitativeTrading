# M3 HISTORY-BATCH250 真实恢复执行任务单

日期：2026-07-18  
状态：**已获持续 API 授权，按冻结边界执行**

## Baseline 与批次

当前：`3186 total / 249 verified / 2937 missing / planned partial=0 / [INDEX]`。

按 canonical request-id 顺序选择前 250 个 missing：

```text
identity set sha256 = 8347baeeab3f0bc59b394bfe328142031306bd4a7bcbcd8a1930ca4050394792
first id = 183e56b39a1701af40f04b61da62720c573940c0ec9287c01bb3ce46d56a7bcb
last id  = 2c32839fcdfaac19c80753d3cc7da435c22e81493673cc2d4085a9dfd73a1a25
adj_factor=47, daily=51, dividend=48, stk_limit=45, suspend_d=59
```

唯一网络命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

最多 250 个新 committed identity；冻结 `max_attempts=5`，合同上限 1,250 attempts。已有 verified 不计入额度。

## 停止条件

- 只运行一次，失败即停，不补跑余额。
- 不提高 60/min 配置、不并发 writer、不放宽 empty/row-limit/policy、不 sleep 绕限频。
- 不启动 REFERENCE/PREPARE/PUBLISH/run-all，不调用已知无权限端点。
- 不输出 token/底层 cause；实际 attempt 数不可验证时只报告上限。

## 成功验收

预期：`new=250 / verified=499 / missing=2687 / partial=0 / [INDEX] / INCOMPLETE`。

执行后运行生产 status，并对全部现有 receipt 逐条调用 `verify_tushare_receipt`；核对 raw/metadata/content/policy 闭包、endpoint 增量、计数守恒和计划外 INDEX/月窗目录。用户 24 小时流程简化期间由主 Agent 直接执行验证，不声称外部独立初验。
