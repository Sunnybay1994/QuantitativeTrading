# M3 G8C-C1 U12 R1：Public CLI 三场景完整运行报告

日期：2026-08-13  
结论：**STOP（命中冻结的 120 分钟无终态停止条件）**

## 1. 执行范围

- Windows Python 3.12 环境 `m3chain312`。
- honest 300 证券 public producer；未缩小业务域，未注入 private capability/result。
- 目标测试为 public `backtest` CLI 首次发布，并在首次成功后以同一参数验证 completed resume。
- 只启动一个 pytest 进程；运行期间未重启、未并发重复。

## 2. 终态证据

- 到 120.0 分钟时进程仍未自然结束，CPU 累计约 `2832.7s`，工作集约 `738.2MB`，表明仍在计算而非已退出但日志未读取。
- stdout/stderr 均为空；测试使用 `capsys`，在 pytest 节点结束前不会形成可计的断言摘要。
- 因首次 CLI 尚无自然终态，不能声明首次发布、29 outputs、receipt 或第二次 completed resume 通过。
- 按任务单 §3 在 120 分钟处终止唯一进程；不延长、不重跑、不把超时记为 PASS。

## 3. 清理

终止后依据本次创建时间与 fixture 固定命名精确识别并清理：

- 唯一 `_f0r2_*` stage root；
- 唯一对应 G1 release root；
- `configs/research/_m3_f0r2_chain_session.toml`；
- U12 零字节 stdout/stderr 日志目录。

清理前确认目标均位于当前 worktree、不是 reparse/link，且无残留 U12 Python 进程；清理后四个目标均不存在，`_f0r*` 计数为 `0`。

## 4. 结论与下一步

U11 已证明 0.5x 单场景 actual replay 可完成；U12 表明当前 honest producer + public CLI 三场景首次发布在冻结的 120 分钟窗口内无法取得终态。下一步应先做只读耗时分解或重冻可接受的运行窗口/复用边界，不能直接重复同一长命令，也不能以私有注入迁就测试。
