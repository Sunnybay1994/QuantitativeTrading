# M3 HISTORY-BATCH500 真实恢复执行任务单

日期：2026-07-18  
状态：**已获持续 API 授权，按冻结边界执行**

Baseline：`3186 total / 499 verified / 2687 missing / partial=0 / [INDEX]`。

前 500 个 canonical missing identity：

```text
identity set sha256 = 493258ecb8d67a63357928f784a2cd0939ea0128aab18acb56e982c81c87c7ff
first id = 2c46911536d4c4b48f2cb36fb2648640003055e50598f54bc788b2ae7b868b45
last id  = 52d31e4ea6464e68d03974bea5529a7c31efead61b3d02fc18faf05242ceacaf
adj_factor=109, daily=112, dividend=93, stk_limit=103, suspend_d=83
```

唯一命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 500
```

最多 500 个 committed identity、每个最多 5 attempts，合同上限 2,500 attempts。只运行一次，失败即停且不补余额；不提高 60/min、不并发、不放宽 empty/row-limit/policy、不绕限频、不启动其他阶段。

全成功预期：`verified=999 / missing=2187 / partial=0 / [INDEX] / INCOMPLETE`。执行后生产 status + 全 receipt verifier + raw partial 审计；核对 endpoint 增量、计数守恒及 INDEX/月窗计划外目录。用户 24 小时流程简化期间由主 Agent 直接执行验证，不声称外部独立初验。
