# M4-P8-RUN-0B1 R3：解释器 Teardown 析构边界返工交付报告

日期：2026-08-09

角色：原实现 Agent 最小返工

状态：R3 实现与自测完成，待全新上下文独立复验和主 Agent 终验

## 1. 返工内容

唯一生产改动位于 `PaperBrokerStore` 资源释放边界：

- `__del__` 不再调用严格 public `close()`；改为 destructor-only best-effort release；
- 析构的 outer boundary 与逐 handle release 均捕获 `BaseException`，覆盖 interpreter teardown 时 module global、
  dynamic import 或 platform close primitive 已不可用的情况；
- 析构路径没有 print、log、warning，也不会把异常交给 `sys.unraisablehook`；
- public `close()` 保持严格：尝试释放全部 handle/fd，任一真实失败后向 caller 返回固定、脱敏的
  `PAPER_BROKER_CLOSE_FAILED`，不泄露底层路径或异常 context；
- Windows `CloseHandle` false 现在明确进入上述稳定失败语义。

policy、replay、anchor、CAS、EOD、gateway 和 evidence 语义均未改变。

## 2. 新增反例

- monkeypatch public `close()` 为 hostile failure，直接执行析构：不调用 public close、无 unraisable、handles 清空；
- monkeypatch platform guard close 全部失败：显式 `close()` 尝试每个 handle，最终只返回稳定错误且
  `cause/context is None`；
- fresh subprocess 创建 broker store 后故意不显式 close：正常解释器退出，return code 0，stdout/stderr
  均为空。因此不存在 `Exception ignored`、traceback、worktree/Miniforge/TOKEN/path marker；
- 同一 subprocess 测试在 Windows 原生和 WSL base `/mnt/f` 均实际执行。

## 3. 验证结果

Windows 原生 Miniforge：

- 定向 pytest：`25 passed`；
- 两个生产文件与两个测试文件 Ruff：PASS；
- 两个生产文件 mypy：PASS。

WSL Miniforge base，当前 `/mnt/f`：

- 定向 pytest：`25 passed`；
- 同范围 Ruff：PASS；
- 两个生产文件 mypy：PASS。

R2 F1–F3 formal/replay-anchor/CAS、UNKNOWN restart、partial/cancel、EOD、busy/crash 等全部包含在上述回归中。
当前 WSL 仍是 WSL1/DrvFS，只表示工程兼容，不是 ext4 Gate。

## 4. 边界

- 未触碰 formal root/journal、未注册或启动 soak、未联网、未 add/commit；
- 本次只修改 B1 白名单生产文件、测试文件与本唯一 R3 报告；
- M4 仍为 `WAITING_FOR_SOAK_EVIDENCE`，需独立 R3 复验和主 Agent 终验。
