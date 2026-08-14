# M3 G8C-C1 R2：单次长链证据与静态门禁返工任务单

日期：2026-08-12  
状态：**外部实现 FAIL；不得进入独立初验；待主 Agent 冻结 R3**  
前置：[M3_G8C_C1_R1_外部实现中止与返工记录.md](M3_G8C_C1_R1_外部实现中止与返工记录.md) **FAIL**  
基础合同：[M3_G8C_C1_R1_Backtest命令接线任务单.md](M3_G8C_C1_R1_Backtest命令接线任务单.md)

## 1. 唯一目标

保留 R1 已形成的 C1 CLI 候选，仅闭合两项交付门禁：

1. 修复 C1 白名单内 3 个真实 mypy 诊断；
2. 以**单次、持久、可审计**方式完成最终 Windows honest integration。

本轮不是重新设计 CLI，不允许扩展 C2、tracking、run-all、业务算法或上游 capability。

## 2. 冻结不变量

R1 §2–§5 的 public CLI、config 原路径、exact 调用顺序、canonical JSON、稳定退出码、零写、resume 和命令隔离合同全部保持不变。除非 focused 测试证明 R1 候选违反这些冻结合同，否则生产代码不应扩大修改。

任何 R1 候选的新功能缺陷必须先写明“现象—根因—规则—最小复现—测试—通过条件”；若修复需要越过本任务白名单，立即停止并回报主 Agent。

## 3. Mypy 最小返工

目标诊断仅为：

- `tests/unit/test_m3_run_cli.py:546`：`object.raw_config_sha256`；
- `tests/unit/test_m3_run_cli.py:552`：`object.source_files`；
- `tests/unit/test_m3_run_cli.py:553`：`object.code_version`。

允许在该测试内使用显式、窄、可读的类型注解、`cast` 或 exact `isinstance`/type 证明；不得：

- 增加 `# type: ignore`、关闭错误码、使用 `Any` 掩盖；
- 改生产类型来迁就测试；
- 修改 `tests/unit/test_m3_reference.py` 等白名单外既有文件；
- 用默认 follow-import 产生的白名单外历史诊断冒充 C1 缺陷。

冻结目标命令：

```powershell
D:\Miniforge3\python.exe -m mypy --follow-imports=silent `
  src/quant/research/run_m3.py `
  tests/unit/test_m3_run_cli.py `
  tests/unit/test_m3_g8c_c1_backtest_cli.py `
  tests/integration/test_m3_g8c_c1_backtest_cli.py
```

必须 `Success: no issues found in 4 source files`。

## 4. 单次长链证据协议

只有以下前置全部 PASS 后，才允许启动最终 honest integration：

1. focused unit；
2. 定向 Ruff；
3. §3 的定向 mypy；
4. cold import；
5. scoped diff/whitespace/白名单检查；
6. 最终候选文件 SHA-256 已记录，且没有其他 writer 会话。

最终命令仍为：

```powershell
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_m3_g8c_c1_backtest_cli.py
```

约束：

- 最终 revision 只允许启动一次，最长预算 10800 秒；
- 启动时立即把命令、候选 SHA、PID、开始时间写入本轮唯一、明确命名的持久证据文件；
- stdout/stderr 必须重定向到独立文件，并在同一受控 wrapper 自然回收进程后追加结束时间、pytest 摘要和 EXIT；
- 证据文件可放系统临时目录，交付报告必须记录其绝对路径、SHA-256 和必要摘要；不得把秘密或大日志复制进仓库；
- 运行期间只低频检查同一 PID 是否仍存活；不得启动第二个 pytest，不得以读取活动日志替代自然等待；
- 若 EXIT 非零、进程被意外终止、摘要不可回收或 teardown 未证明，R2 立即 FAIL：停止、保留证据、写失败报告，不得重跑；下一次运行必须由主 Agent另冻 R3；
- 测试结束后确认无 pytest 子进程、无本轮 owned root 残留；不得扫描或删除非本轮目录。

## 5. 文件白名单

实现 Agent 只允许修改或新增：

1. `tests/unit/test_m3_run_cli.py`：仅修复 §3 类型证明；
2. `src/quant/research/run_m3.py`：原则上不改；只有 focused 反例证明 R1 生产缺陷时可作最小修复；
3. `tests/unit/test_m3_g8c_c1_backtest_cli.py`：仅为确凿生产缺陷补回归；
4. `tests/integration/test_m3_g8c_c1_backtest_cli.py`：仅为确凿 teardown/证据缺陷补回归；
5. `docs/M3实施与Agent交接.md`：只同步 C1 R2 状态；
6. 本 R2 任务单状态；
7. 唯一交付报告 `docs/agent/M3_G8C_C1_R2_单次长链证据与静态门禁返工交付报告.md`。

R1 任务、R1 中止记录、R1 报告路径、C0 support/tests/reports 和所有上游生产/测试保持只读。禁止联网、add/commit/push、正式 artifact/data 写入。

独立初验只允许新增唯一报告：

`docs/agent/M3_G8C_C1_R2_单次长链证据与静态门禁返工独立复验报告.md`

## 6. 验证矩阵

### 6.1 Windows 标准反馈环

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g8c_c1_backtest_cli.py tests/unit/test_m3_run_cli.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m ruff check src/quant/research/run_m3.py tests/unit/test_m3_run_cli.py tests/unit/test_m3_g8c_c1_backtest_cli.py tests/integration/test_m3_g8c_c1_backtest_cli.py
D:\Miniforge3\python.exe -m mypy --follow-imports=silent src/quant/research/run_m3.py tests/unit/test_m3_run_cli.py tests/unit/test_m3_g8c_c1_backtest_cli.py tests/integration/test_m3_g8c_c1_backtest_cli.py
```

另做 fresh subprocess cold import，证明 `run_m3` 不加载 Qlib、LightGBM、MLflow、C0 resolver 或 G8 stage 重依赖。

### 6.2 Windows honest integration

只按 §4 单次执行；不得在实现者会话内“先试跑一次、再跑最终一次”。

### 6.3 WSL1/base

- focused unit、Ruff、目标 mypy、cold import；
- `platform_supports_renameat2_noreplace()==False` 时，integration 必须在构建链和任何写入前 narrow skip；
- DrvFS/wslfs 只算兼容证据，不宣称 Linux/ext4 Gate。

## 7. 停止条件

命中任一项立即停止并写失败交付报告，不启动或重启长链：

1. 需要修改 R1 禁止的上游模块、C0 support、schema/config 或正式 data；
2. 需要 `Any`/ignore、fake/private verified、`SimpleNamespace`、`object.__new__`/`__setattr__`；
3. focused/静态/cold 未绿；
4. 长链已被启动一次后出现任何失败或证据丢失；
5. 无法证明 teardown、owned root 清理或无残留子进程；
6. 外部服务连接异常导致会话无法诚实回收终态。

## 8. 外部闭环

- 实现：新的外部 Cursor `--model auto` 会话，只按本任务书返工、自测并写唯一 R2 交付报告；不得宣布 Gate。
- 初验：实现交付完整后，另一未参与实现的全新 Cursor `--model auto` 会话只读核对，并补实现者未使用的对抗；生产与实现测试只读。
- R2 初验 PASS 后才进入主 Agent 最终验收；C1 主验 PASS 后才可冻结 C2。
- UA-AGENT-001 已获项目级长期批准，无需逐会话申请；仍严格排除秘密、ignored 私密配置、正式 data、联网扩散、add/commit/push。
