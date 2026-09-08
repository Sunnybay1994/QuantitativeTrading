# M3 G8C-C1 U1 R1：G8 Build 分层透明诊断报告

日期：2026-08-12  
角色：外部 Cursor `auto` 独立诊断；主 Agent 仅执行异常会话后的安全清理与证据核对  
结论：**FAIL / 证据不足；不得重跑 U1，不得据此修改生产或宣布任何 Gate**

## 1. 现象

外部 Cursor `auto` 会话于 2026-08-12 11:42:06 启动，并在 11:47:40 创建单次诊断包装器与 pytest
进程。会话结束后出现以下不可接受终态：

- Cursor 自身 stdout/stderr 文件均为 0 字节；
- 任务要求的唯一诊断报告不存在；
- 持久 evidence 只有 `STATUS=STARTED`、wrapper PID 与 pytest PID，没有结束时间、墙钟或整数 `EXIT`；
- stdout/stderr 均为空；
- `phase_a_observe.json` 不存在；
- wrapper、pytest、Cursor 进程均已退出，无法继续自然等待；
- integration 测试仍停留在临时观察 revision，未由外部会话完成 teardown。

因此本轮没有可用于判断 G7F/G7E/G7D、fixture 或 publication 首个失败边界的证据。最后成功边界、
LightGBM warning 或空日志都不能替代根因证据。

## 2. 已保留的失败证据

持久目录：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u1-r1-g8-build-diagnostic\`

| 文件 | 长度 | SHA-256 |
|---|---:|---|
| `M3_G8C_C1_U1_R1_diagnostic_evidence.txt` | 874 | `827d44d8bc9eb9794d7fbf1182951d6fed9333bbd11534d6affac32ee98c0159` |
| `M3_G8C_C1_U1_R1_diagnostic_stdout.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `M3_G8C_C1_U1_R1_diagnostic_stderr.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `run_u1_r1_diagnostic.ps1` | 3931 | `ba3b18144457fce4af02983182ab2d52ce565d897e9a4e9c9f0b311bfadc22d4` |

evidence 明确记录：`MODEL=auto`、`PYTEST_PID=42864`、候选 integration SHA
`d323321dc8abb42390d15babf97edf744fea4492b2e491a81d2ebbe03e2b30e7`，但没有完成记录。

## 3. 安全清理与恢复

主 Agent 确认没有遗留的 Cursor、pytest 或 `m3chain312` 进程后，只移除了 integration 测试中的临时
观察器/import/env marker；没有修改生产、C0 support、配置或其他测试。恢复结果：

- `tests/integration/test_m3_g8c_c1_backtest_cli.py` SHA-256 精确回到
  `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2`；
- `rg` 不再发现 `M3_G8C_C1_U1`、`_U1LayerObserver` 或 `_install_u1`；
- Ruff：PASS；
- mypy：首次未设置正确源码搜索路径时误导入已安装包而报 2 个 `import-untyped`，不计证据；设置当前
  工作树 `MYPYPATH=...\src` 后单文件 PASS。

## 4. 根因与规则判断

- **已证明的直接原因**：外部诊断会话/其包装器没有留下可审计终态，违反任务单 §5、§8、§9。
- **未证明的外部中断原因**：现有证据不足以区分 Cursor 会话生命周期、包装器故障、进程树回收或其他
  外部服务异常，报告不作猜测。
- **未定位的产品原因**：C1 R3 的 `STAGE_BUILD_FAILED` 仍未进一步定位。
- **应遵循规则**：同一 U1 revision 已启动后禁止重跑；不能用空日志、最后开始事件或警告猜根因。

## 5. 下一步与通过条件

冻结 U2，拆开“准备观察器”“唯一长链生命周期”“终态取证”三项职责：

1. 外部 Cursor `auto` 只在系统临时目录准备独立 pytest plugin 与单进程包装器，不启动长链、不改仓库测试；
2. 主 Agent 使用准备好的包装器启动并等待唯一 Windows 长链，包装器独立于 Cursor 会话，必须留下整数
   EXIT、observe、stdout/stderr、PID、时间与哈希；
3. 长链结束后由新的 Cursor `auto` 独立只读取证，写 U2 诊断报告；
4. U2 必须定位第一个真实失败边界，或诚实给出仍无法区分的精确证据；不得重复该长链。

U2 通过后才可冻结最小实现返工；本轮不进入实现或独立初验。
