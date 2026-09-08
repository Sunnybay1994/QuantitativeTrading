# M3 G8C-C1 R3：真实 CLI 失败定位与单次终验返工任务单

日期：2026-08-12  
状态：**外部实现 FAIL；不得进入独立初验；待主 Agent 冻结上游/R4**  
基础合同：[M3_G8C_C1_R1_Backtest命令接线任务单.md](M3_G8C_C1_R1_Backtest命令接线任务单.md)  
R2 失败：[M3_G8C_C1_R2_单次长链证据与静态门禁返工交付报告.md](M3_G8C_C1_R2_单次长链证据与静态门禁返工交付报告.md)

## 1. 已冻结事实

R2 最终候选的短门禁全部通过，但唯一 Windows honest integration 于
`2026-08-12T03:25:54+08:00` 至 `04:32:48+08:00` 自然结束：

- pytest PID `11088`，`EXIT=1`；
- `1 failed, 1 skipped, 196621 warnings in 4010.34s`；
- 失败为 `tests/integration/test_m3_g8c_c1_backtest_cli.py:109` 的
  `assert code == 0`，实际 `code == 5`；
- stdout 恰一行且可解析为 JSON，但测试先读取了 `capsys`，失败 traceback 没有展示 payload；
- public formal chain 已构建完成，失败位于 actual CLI resolver/stage 路径；
- pytest/wrapper 已退出，本轮 `_f0r*` owned root 无残留，禁止重跑 R2。

持久证据：

`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-r2-honest-integration\M3_G8C_C1_R2_honest_integration_evidence.txt`

SHA-256：`ee8fa3d3ef555cd4027ee64b2e6ffa217fb1e05adab67abd31bd11d2c477f447`。

R2 四个候选 SHA-256 已由主 Agent 复核：

| 文件 | SHA-256 |
|---|---|
| `src/quant/research/run_m3.py` | `573fd24eb363181f2d98edd69b71bf94d6a885f902de26e68b25987fee059060` |
| `tests/unit/test_m3_run_cli.py` | `f26023a01d8cea242788c6b701c0d5a53c4a2116fa279e730e972a130adceb32` |
| `tests/unit/test_m3_g8c_c1_backtest_cli.py` | `5af772327f774d9560096c014f5db2f261a9c1691a0808ae684891f358a0afca` |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | `9549b74b111851271b53dbc4da5a33bcd622d2c6deaa653d8a8e17d9d6dbab5c` |

## 2. 唯一目标

在不放宽 C1 public 合同、不重跑 R2、不修改已主验上游语义的前提下：

1. 用一次可审计、透明的 Windows 真实链诊断，取得失败 payload 与实际抛出边界；
2. 按“现象—根因—规则—最小复现—新增测试—通过条件”闭合确凿缺陷；
3. 短门禁全绿后，用最终 revision 仅运行一次无诊断包装的 Windows honest integration；
4. 最终成功、复用、canonical JSON、零越界写入和 teardown 均有持久证据。

本轮不是重做 C0/G8/G7，也不实现 C2、tracking、`run-all`、MLflow 或新的 CLI 命令。

## 3. 不变量

R1 §2–§5 的下列合同保持不变：

- `backtest --config --snapshot-id --fold --horizon [--no-resume]`；
- config 必须为 project-root 内原始、canonical、非 link/alias 路径；
- `load_m3_config` → `resolve_formal_backtest_cli_inputs` →
  `run_formal_backtest_stage`，每次按 public exact 输入调用；
- 成功只输出一行 canonical JSON，字段精确为命令、snapshot/fold/horizon、work key、
  `reused` 与 `stop_stage=backtest`；
- 稳定失败码与退出码保持现有映射，hostile 异常不泄露 cause/context/path/raw marker；
- CLI 不读取或写入 tracking/MLflow，不生成缺失上游，不接 fake/private capability；
- production 不引入调试输出、环境开关、日志旁路或测试专用 API。

## 4. Phase A：一次透明诊断长链

### 4.1 诊断测试改动

只在 `tests/integration/test_m3_g8c_c1_backtest_cli.py` 内增加临时透明观察：

1. `assert code == 0` 必须永久改为 `assert code == 0, payload`，以后失败必须展示已脱敏的 canonical payload；
2. 保存 `run_m3.resolve_formal_backtest_cli_inputs` 与
   `run_m3.run_formal_backtest_stage` 的原 callable；
3. 包装器必须把原参数原样传入，并把原返回值/原异常原样返回或重新抛出；不得缓存、替换、伪造或少调；
4. 仅记录以下非秘密诊断字段：边界名、调用次数、异常 exact
   `type.__module__ + type.__qualname__`、exact `str` 类型的 public `.code`、exact `int`
   类型的 public `.exit_code`、`__cause__ is None`、`__context__ is None`；
5. 禁止记录异常 `str/repr`、路径、hash 以外原始内容、DataFrame、配置内容或秘密；
6. 诊断包装只存在于 Phase A revision；最终验收 revision 必须移除包装器，但保留
   `assert code == 0, payload`。

透明包装仍必须真实执行 C0 resolver 和 G8 stage，不属于 mock/fake。调用次数必须与未包装路径一致。

### 4.2 诊断运行协议

在运行前先完成 focused pytest、Ruff、目标 mypy、cold import、scoped diff、候选 SHA、无其他 writer/pytest
核对。然后仅启动一次：

```powershell
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider \
  tests/integration/test_m3_g8c_c1_backtest_cli.py
```

使用独立 wrapper 把 PID、开始/结束时间、命令、候选 SHA、`MODEL=auto`、stdout/stderr、pytest 摘要和 EXIT
写入新的 `m3-g8c-c1-r3-diagnostic` 持久目录。运行期间只低频等待同一 PID，不读活动日志、不启动第二次。

Phase A 预期可 FAIL；它只用于取得证据，不是验收。若 evidence/摘要/诊断字段丢失，R3 立即 FAIL，禁止再跑诊断链。

## 5. 根因裁决与最小修复

Phase A 后必须先在交付报告写全六项闭环：

1. 现象：canonical failure payload、exact 边界和调用次数；
2. 根因：哪一个输入/身份/路径/receipt/阶段不变量被违反；
3. 应遵循规则：引用 R1/C0/G8/G7 的现有权威合同；
4. 最小复现：优先构造秒级 focused regression，不再依赖 60 分钟 fixture；
5. 新增测试：正向、反例、异常脱敏和调用次数；
6. 通过条件：短门禁与 Phase B 最终长链。

若 payload 为 `M3_COMMAND_FAILED`，不得把它当根因；必须结合透明观察证明原异常 exact type/public code。
不得通过扩大 catch、改成成功返回、弱化 exact type/identity、跳过 verifier、删除 receipt/closure 校验或预建
backtest root 来“修绿”。

允许的生产修复原则上仅限 `src/quant/research/run_m3.py` 的 C1 seam。若证据表明缺陷属于已主验的
`formal_cli_resolve.py`、`backtest_stage.py` 或更上游模块，立即停止并写 FAIL 报告，由主 Agent 另冻对应上游返工；
本轮不得顺手修改上游。

## 6. Phase B：最终 revision 单次 honest integration

只有根因闭环、focused regression、Windows/WSL 短门禁、Ruff、目标 mypy、cold import、diff/白名单、最终 SHA、
无其他 writer/pytest 全部 PASS 后才可开始。Phase A 的透明包装必须已移除。

最终 revision 只允许启动一次与 §4.2 相同的 integration 命令，使用独立
`m3-g8c-c1-r3-final` 持久证据目录。约束：

- 最大预算 10800 秒；同一受控 wrapper 自然回收；
- 运行期间不读活动日志、不重启、不并发；
- 必须 `EXIT=0`，Windows 节点 PASS、平台不适用节点 narrow skip；
- stdout success payload exact、第二次 CLI 调用的 `reused=True` 契约按测试覆盖；
- teardown 后无 pytest 子进程、无本轮 `_f0r*`、stage/config/G1 owned root 残留；
- 若失败、超时、证据丢失或 teardown 不完整，R3 FAIL，禁止重跑，主 Agent另冻 R4。

## 7. 文件白名单

实现 Agent 只允许修改/新增：

1. `src/quant/research/run_m3.py`：仅确凿 C1 seam 缺陷的最小修复；
2. `tests/integration/test_m3_g8c_c1_backtest_cli.py`：Phase A 透明诊断与永久 payload 断言；最终 revision 移除透明包装；
3. `tests/unit/test_m3_g8c_c1_backtest_cli.py`：根因的秒级 focused regression；
4. `tests/unit/test_m3_run_cli.py`：保持 R2 类型证明，仅在同一根因需要时最小补测；
5. `docs/framework/M3实施与Agent交接.md`：只同步 C1 R3 状态；
6. 本任务单：只更新状态；
7. 唯一交付报告：
   `docs/framework/agent/M3_G8C_C1_R3_真实CLI失败定位与单次终验返工交付报告.md`。

R1/R2 历史任务与报告、C0 support/tests/reports、`formal_cli_resolve.py`、`backtest_stage.py`、G1–G7、config/schema、
其他测试均只读。禁止联网、add/commit/push、正式 artifact/data 写入和删除历史脏文件。

独立初验仅在 Phase B PASS 后由另一全新 Cursor `auto` 会话进行，生产与实现测试只读，只能新增：

`docs/agent/M3_G8C_C1_R3_真实CLI失败定位与单次终验返工独立复验报告.md`

## 8. 短门禁

Windows：

```powershell
D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_g8c_c1_backtest_cli.py tests/unit/test_m3_run_cli.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m ruff check \
  src/quant/research/run_m3.py tests/unit/test_m3_run_cli.py \
  tests/unit/test_m3_g8c_c1_backtest_cli.py tests/integration/test_m3_g8c_c1_backtest_cli.py
D:\Miniforge3\python.exe -m mypy --follow-imports=silent \
  src/quant/research/run_m3.py tests/unit/test_m3_run_cli.py \
  tests/unit/test_m3_g8c_c1_backtest_cli.py tests/integration/test_m3_g8c_c1_backtest_cli.py
```

另做 fresh subprocess cold import，证明不加载 Qlib、LightGBM、MLflow、C0 resolver 或 G8 stage。

WSL1/base：同一 focused unit、Ruff、目标 mypy、cold import；`renameat2=False` 时 integration 必须在构建链前
narrow skip。DrvFS/wslfs 只算兼容证据，不宣称 ext4 Gate。

## 9. 停止条件

命中任一项立即 FAIL，不启动下一条长链：

1. Phase A 透明观察改变调用参数、次数、返回值、异常或 public 行为；
2. Phase A evidence/诊断字段不可回收，或有人启动第二个诊断 pytest；
3. 根因属于白名单外已主验模块、需要改 schema/config/C0 support/正式 data；
4. 需要 fake/private verified、`SimpleNamespace`、`object.__new__`/`__setattr__`、`Any`/ignore 掩盖；
5. 需要弱化 fresh、receipt、identity、path、no-clobber、zero-write 或异常脱敏合同；
6. 任一短门禁未绿；
7. Phase B 最终长链非零、超时、证据丢失或 teardown 不完整；
8. 外部服务异常导致无法诚实回收终态。

## 10. 外部闭环

- 实现：新的外部 Cursor 会话，显式 `--model auto`，只按本任务书工作并写唯一交付报告；不得宣布 Gate。
- 初验：仅在 Phase B PASS 后，由未参与实现的另一全新 Cursor `--model auto` 会话只读审查并补未使用对抗。
- 初验 PASS 后才进入主 Agent 主验；C1 主验 PASS 后才可冻结 C2。
- UA-AGENT-001 已长期批准，无需逐会话申请；秘密、ignored 私密配置、正式 data、联网扩散和 git 写操作仍禁止。
