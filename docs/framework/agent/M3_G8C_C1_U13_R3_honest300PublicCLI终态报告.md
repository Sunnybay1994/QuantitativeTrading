# M3 G8C-C1 U13 R3 honest 300 Public CLI 终态报告

日期：2026-08-14  
结论：**Windows honest 300 证券、三成本场景 public CLI 首发与 completed resume 在同一最终 revision PASS。**

## 1. 运行边界

- worktree：`artifacts/dev_worktrees/m3-g4-formal`
- revision：`706ab2cd1f6923fed6eb5b31e78d22bc9d1c3a17`
- Python：Windows Miniforge `m3chain312`
- 唯一业务 PID：`10952`
- 资源：`BelowNormal`、affinity `255`、Polars/OMP 4、OpenBLAS/MKL/NumExpr 2
- 测试：`test_windows_actual_cli_happy_path_zero_write_boundary_and_canonical_json`

没有缩小 300 证券业务域，没有替换三成本场景，没有注入 private capability/result，也没有并发或重复启动。

## 2. 自然终态

原始 stdout：

```text
.                                                                        [100%]
1 passed, 1123808 warnings in 9716.55s (2:41:56)
```

stderr 为空。测试 PASS 表明同一测试函数内的以下断言全部真实执行：

1. 首次 public CLI 返回 code 0、canonical 单行 JSON、`reused=false`；
2. 只新增 exact backtest 29 outputs、receipt 与允许的 advisory `.writer.lock`；
3. 第二次同参 public CLI 返回 code 0、同一 payload 且 `reused=true`；
4. G1 tree 未写，completed resume 后 stage business tree 逐文件 size/mtime 零变化；
5. fixture teardown 正常运行，session-owned roots 按既有身份规则清理，仓库 `_f0r*` 残留为 0。

## 3. 原始证据摘要

- `stdout.log` SHA-256：`6472616435E39717B15220D93641DA4850E5B871FCED252BE5F0EC230A21BAC3`
- `stderr.log` SHA-256：`E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`
- `status.json` SHA-256：`B01EB491188476DF76DE8D54DF1B8326992A1C51EAC3F9868D64C2A8CC116EBC`
- 证据目录：`artifacts/agent_runs/m3-u13-r3/`

`status.json.state=FINISHED`、finished_at 存在，但 `exit_code=null`。这是包装器读取 `Start-Process` 已退出对象 ExitCode 的元数据缺口；没有用它替代 pytest 业务摘要，也没有修改原始文件。后续 runner 应使用可可靠保存整数 exit code 的进程等待方式。

## 4. 结论边界

本轮关闭 UA-M3-001 的 Windows honest 300 首发/completed-resume 性能与零写工程准入。它不证明 Linux/ext4 atomic publication，不证明当前真实远端 MLflow/tracking 可用，也不单独等于 M3 总 Gate。后续应把本终态纳入 M3 G9/CLI 总体状态与统一集成分支，再处理尚开放的真实 tracking 与平台项。
