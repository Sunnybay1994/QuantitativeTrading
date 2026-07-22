# M3 HISTORY-FINAL77 真实恢复执行任务单

## 冻结最终集合

- 前置：verified `3109`、missing `77`、partial `0`
- 数量：`77`（全部剩余 HISTORY identity）
- ordered request-id SHA-256：`ed3eb73263a75ad1dfb8e3f2bcfcab946e10f05cdf4e21d4fea08a3c1d7ca522`
- endpoint：`adj_factor=17`、`daily=15`、`dividend=10`、`stk_limit=14`、`suspend_d=21`
- 首个：`fa8ffd3a98ce77f53c85aaedee5ac57bde6cbd25fae75b7f70e831605c8a0390`（`daily/600406.SH`）
- 末个：`ffd6a421969d74c5f64cd973b469a7e756ab26e34c6e175b997e010b3041e58a`（`adj_factor/002129.SZ`）

## 唯一命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 77
```

## 约束与通过条件

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功后全量生产验证必须为 history `3186`、verified `3186`、missing `0`、partial `0`。
- 只有收据闭包通过后才认定 HISTORY 数据回填完成；不在本命令中构建 candidate、prepare 或 publish。

