# M3 HISTORY-BATCH250 R8 真实恢复执行任务单

## 冻结集合

- 前置：verified `1227`、missing `1959`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`3ebc5e1ce1966fe6dc913883ca407fe4ef2d0072f24479041b380b67aac59ac0`
- endpoint：`adj_factor=54`、`daily=40`、`dividend=42`、`index_daily=1`、`stk_limit=57`、`suspend_d=56`
- 首个：`64f14cea02999af6a38dc1e9d201098af9e57c08dbe841ebb0bb219d10ccf65a`（`adj_factor/600535.SH`）
- 末个：`7a792deb497e77276e66390e57b0089b0152132ca7e6ceef29f1afbedca09aa8`（`daily/300496.SZ`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者逐请求串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- `index_daily` 仍属于冻结 HISTORY plan，使用同一生产 verifier 与 endpoint policy，不把它误计为已完成 INDEX stage 的 127 张 index_weight。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `1477`、missing `1709`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

