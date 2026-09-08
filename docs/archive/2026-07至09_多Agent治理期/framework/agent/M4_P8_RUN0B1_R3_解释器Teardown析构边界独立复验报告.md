# M4-P8-RUN-0B1 R3：解释器 Teardown 析构边界独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的全新独立复验 Agent  
结论：**PASS**

## 1. 范围与边界

已完整核对 `M4_P8_RUN0B1_独立DurablePAPERBroker任务单.md` §14、R2 FAIL 报告与
`M4_P8_RUN0B1_R3_解释器Teardown析构边界返工交付报告.md`，并只读审查生产实现和实现者测试。
除本报告外未写入项目文件；所有对抗 fixture 均在系统临时目录。未建 formal root，未注册或
启动 runner/soak，未联网，未 add/commit。

R3 的生产语义收缩为 `PaperBrokerStore` 资源释放边界：`__del__` 不再复用严格 public
`close()`，而是逐 handle 的 best-effort 释放并以内外两层 `BaseException` 边界静默收口。policy、
replay、anchor、CAS、EOD、gateway 与 evidence 语义未因本修复改变。

## 2. R3 冻结条件复验

### 2.1 fresh subprocess 退出清洁 — PASS

Windows 原生与 WSL base 都实际执行了 fresh subprocess 回归：创建并保留 open store 到解释器
退出，不显式调用 `close()`。两平台均断言 return code 0，且 stdout/stderr **bytes 形态均严格
为空**；因此不存在 `Exception ignored`、traceback、worktree/Miniforge 绝对路径或 TOKEN marker
泄漏。

### 2.2 实现者未用的 module teardown 顺序探针 — PASS

独立新增了不写入仓库的顺序探针：

- Windows：在 store 仍持有全部句柄时，先令 module `sys` 变为 `None`、`sys.modules["ctypes"]`
  变为 `None`，保留原始 `_guard_close` 再触发 `__del__`。`ctypes`/import teardown 引发的失败被
  destructor-only 边界吸收，`sys.unraisablehook` sentinel 为空，handle tuple 被收窄为空。
- Windows 补充：先将 module `_guard_close` 置 `None`；另一实例用自定义 `BaseException`
  模拟底层 `CloseHandle` hostile failure。逐 handle 均被尝试，无 unraisable。
- WSL/POSIX：先将 module `_guard_close` 与 `os` 分别置为不可用状态；另用
  `BaseException` 模拟底层 `os.close` hostile failure。所有 handle 均经过尝试，无
  print/log/warning/unraisable。

独立输出：

```text
WINDOWS_INDEPENDENT_TEARDOWN_ORDER_AND_CLOSE_PASS
WINDOWS_CTYPES_IMPORT_AND_SYS_TEARDOWN_ORDER_PASS
WSL_INDEPENDENT_TEARDOWN_ORDER_AND_CLOSE_PASS
```

### 2.3 显式 public close 严格语义 — PASS

双平台独立探针让第一个底层 close 在真实释放后抛 `BaseException`，后续 handle 仍全部被
遍历。调用者最终只收到 `PAPER_BROKER_CLOSE_FAILED`，且 `cause/context is None`。这证明修复没有
把 public close 的真实失败静默吞掉。

## 3. R2 F1–F3 与主合同回归

25 项双平台定向测试全部通过，覆盖：

- F1：public builder 不能产生 formal policy，direct formal value、duck/subclass store 与 caller 64hex
  不能签发 verified gateway；
- F2：initial snapshot + canonical callbacks 的 fresh replay，account/checkpoint whole-rehash 拒绝，anchor
  增删改/跳号/错 predecessor 拒绝，commit-gap 精确补锚，exact retry 不增加第二 anchor；
- F3：两 writer 同一旧 predecessor 最多首次成功一个，另一个返回稳定 busy/stale，retry
  后 command/event/order/position/cash 经济影响各一次；
- UNKNOWN restart 不重发、partial fill/cancel late fill/final cancel、multi-session EOD finality、
  hostile close 和 fresh import。

未发现 R3 对 replay/anchor/CAS/EOD 的回归。

## 4. 验证结果

Windows 原生 Miniforge，`PYTHONPATH=src`：

- `pytest tests/unit/test_paper_broker_store.py tests/unit/test_paper_durable_gateway.py -q`：
  `25 passed in 12.31s`；
- Ruff（两个生产文件 + 两个测试文件）：PASS；
- mypy（两个生产文件）：PASS；
- fresh import：PASS；
- 独立 teardown/explicit-close 探针：PASS。

WSL Miniforge base，Python 3.13.13，当前内核 `4.4.0-22621-Microsoft`、工作树文件系统
`wslfs`：

- 同组 pytest：`25 passed in 8.55s`；
- 同范围 Ruff/mypy：PASS；
- fresh import：PASS；
- 独立 teardown/explicit-close 探针：PASS。

`git diff --check` 返回 0；仅有既有 Windows LF/CRLF 告警。工作树中其他大量 M4 脏文件和
测试产物在本轮前已存在，本复验未清理、未覆盖。

## 5. 结论与未关闭项

R2 F1–F3 保持关闭，R3 已关闭 Windows 解释器 teardown 的 traceback/绝对路径泄漏。析构路径
在 module globals、`ctypes`/import、`sys`、`os` 和底层 close primitive 部分失效时均静默；显式
public close 仍严格且稳定脱敏。因此 RUN-0B1 R3 **独立复验 PASS**，可进入主 Agent
最终工程验收。

本 PASS 只表示 development durable PAPER broker 工程合同通过独立复验。RUN-0B2 formal
policy/risk/loader、WSL2/ext4 durability Gate、formal runner/scheduler 注册与 28 天 soak 均未关闭；
M4 仍为 `WAITING_FOR_SOAK_EVIDENCE`。
