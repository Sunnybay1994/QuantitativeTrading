# M3 G8C-C1 R1：外部实现中止与返工记录

日期：2026-08-12  
结论：**FAIL / 未交付；不得进入独立初验**  
后续：[M3_G8C_C1_R2_单次长链证据与静态门禁返工任务单.md](M3_G8C_C1_R2_单次长链证据与静态门禁返工任务单.md)

## 1. 现象

外部 Cursor `--model auto` 实现会话写入了 C1 候选生产代码、测试和状态文档，但没有生成冻结要求的唯一交付报告。任务单却被提前标为“外部实现已交付”。

同一候选 revision 的 honest integration 被重复启动：

| 次序 | 时间（Asia/Shanghai） | PID | 终态 |
|---|---:|---:|---|
| 首次 | 02:09:39–约 03:04:09 | 38372 | 进程自然结束，但没有可回收 pytest 摘要或 EXIT；不计 PASS |
| 重复 1 | 03:04:14 | 53768 | 未改 revision 即重复启动；主 Agent 精确终止 |
| 重复 2 | 03:06:39 | 15716 | 未改 revision 再次重复启动；主 Agent终止整个本轮 Cursor 进程树 |

候选文件最后修改时间均不晚于 02:08:07，证明三次启动之间没有代码 revision 变化。Cursor stdout 为空；stderr 只有外部服务连接重试信息，不能提供测试终态。

## 2. 根因

1. 会话未把“长链只启动一次”当作不可恢复的证据约束；首次结果不可回收后直接重跑。
2. 长链没有使用独立、持久、可审计的终态记录来同时保存 PID、开始/结束时间、pytest 摘要和 EXIT。
3. 会话在完成所有冻结门禁和交付报告前提前更新任务状态。
4. 静态门禁没有在长链前闭合：

```text
D:\Miniforge3\python.exe -m mypy --follow-imports=silent \
  src/quant/research/run_m3.py \
  tests/unit/test_m3_run_cli.py \
  tests/unit/test_m3_g8c_c1_backtest_cli.py \
  tests/integration/test_m3_g8c_c1_backtest_cli.py
```

当前精确结果为 3 errors，均在 `tests/unit/test_m3_run_cli.py:546,552,553`：从 `dict[str, object]` 取出的测试对象缺少窄类型证明。

## 3. 应遵循规则

- 任务单 §7.2：最终 revision 的 honest chain 只启动一次；承载层异常时只能追踪同一进程并回收终态。
- 任务单 §8：必须先完成 focused unit、Ruff、mypy、cold import，之后才能启动长链。
- `AGENTS.md` §1.1、§11：实现完成前不得宣布交付；FAIL 必须形成返工任务，再由新外部实现会话闭环。
- `.ai` 的证据规则：缺少摘要/EXIT 的运行不是 PASS；不得以重跑替代丢失的证据。

## 4. 最小复现

1. 上述 `mypy --follow-imports=silent` 命令稳定得到 3 个 C1 自身诊断。
2. `docs/agent/M3_G8C_C1_R1_Backtest命令接线交付报告.md` 不存在。
3. `.tmp-g8c-c1-r1-integration-win.txt` 仅含单个 skip 进度字符，`.tmp-g8c-c1-r1-integration-meta.txt` 只记录第三次启动 PID；二者均不能证明首次运行终态。

## 5. 清理

主 Agent 已终止重复 integration 与本轮 Cursor 的精确进程树。两个由重复测试创建的自有临时根：

- `artifacts/research/m3/_f0r2_3f1796dce502`
- `artifacts/research/m3/_f0r2_6b34f857cb67`

已先确认绝对路径位于目标工作树、为普通目录且不越界，再递归删除并确认不存在。删除不可恢复，但目标仅为中止测试的临时产物；未删除正式 artifact、用户数据或其他历史脏文件。

## 6. 已有正向证据与边界

- focused unit：`80 passed, 1 skipped`；
- 定向 Ruff：PASS；
- 定向 mypy：FAIL（3 errors）；
- honest integration：无可计 PASS；
- 交付报告：缺失。

因此 R1 只能判 FAIL。候选代码保留给 R2 做最小返工，不能据此推断生产合同已通过。

## 7. R2 通过条件

1. 最小修复三个目标 mypy 诊断，不改业务语义、不扩大生产接口；
2. focused unit、Ruff、目标文件 mypy、cold import 全绿后，才能启动长链；
3. 最终 revision 的 honest integration 只启动一次，并由独立持久记录保存 PID、开始/结束、pytest 摘要和 EXIT；
4. 若该唯一长链失败或终态不可回收，R2 立即 FAIL，不重跑；
5. 所有门禁通过后才更新 R2 状态并写唯一 R2 交付报告；
6. 再交给未参与实现的另一全新 Cursor `--model auto` 会话独立初验。
