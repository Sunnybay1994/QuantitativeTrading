# M4-P8-RUN-0B1 R2：formal 来源、重放 Anchor 与并发 CAS 独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的全新独立复验 Agent  
结论：**FAIL**

## 1. 范围与边界

本次完整核对 `M4_P8_RUN0B1_独立DurablePAPERBroker任务单.md` §13、R1 FAIL 报告、R2 交付报告、两份生产实现和两份实现测试。生产代码与实现测试保持只读；除本报告外没有写入项目文件，所有对抗 fixture 均位于系统临时目录；未建 formal root、未注册或启动 runner/soak、未联网。

R2 已关闭 R1 的 F1-F3；但新增 Windows 解释器 teardown 对抗稳定复现一项显式异常脱敏合同破坏，因此本轮仍不进入主 Agent 终验。

## 2. R1 F1-F3 复验映射

### F1：formal 来源收缩与 exact store proof — PASS

- public `build_paper_broker_policy_descriptor` 已删除 `classification` 参数，只产生 exact `classification="development"` value；直接构造 formal value 不能初始化 store。
- factory、gateway、snapshot port 均要求 `type(store) is PaperBrokerStore`，并 fresh 重算 store/policy/gateway identity；duck、subclass 与 caller 64hex 不能签发 verified gateway。
- 独立探针输出：`ADVERSARIAL_F1_PUBLIC_FORMAL_AND_DUCK_SUBCLASS_SELF_MINT_REJECTED`。
- 结论边界：RUN-0B1 没有 formal policy signer；formal policy exact capability 仍待 RUN-0B2。

### F2：initial replay、订单闭合与 retained sequence anchor — PASS（冻结威胁边界内）

- fresh verifier 从 immutable `initial-account.json` 按 journal sequence、canonical operation callbacks 重放账户，并将重放账户与 retained `account_state`、重建订单与 retained `order_state` 做 bytes/value exact 对比。
- 独立构造另一份完全合法的 operation/callback/account/order/journal/checkpoint 整包，并把其 DB logical state 与全部 DB 内 hash 同步替换到目标 store；目标 retained anchor 不变时 fresh open 拒绝：`ADVERSARIAL_LEGAL_WHOLE_PACKAGE_DB_REHASH_REJECTED PAPER_BROKER_ANCHOR_INVALID`。
- 两个 store 的 raw anchor 直接交换被拒绝：`ADVERSARIAL_RAW_ANCHOR_SWAP_REJECTED PAPER_BROKER_ANCHOR_INVALID`。代码核对同时覆盖 exact sequence name set、predecessor anchor digest、sequence、entry/state digest、store identity、root copy 和 symlink/reparse 检查。
- commit 后补锚与补锚前重启由实现测试覆盖；acknowledged anchor 缺失不被补写，exact retry 不创建第二 anchor。
- 边界记录：若具备对 broker root 全量离线写权限，同时协调替换 DB 全包并按目标 store identity 重写对应 anchor，fresh open 可接受该新的自洽历史；独立探针输出 `ADVERSARIAL_LEGAL_WHOLE_PACKAGE_AND_ANCHOR_REHASH_ACCEPTED True`。这与任务单“anchor 不冒充外部数字签名”的明示边界一致，不作为本轮新增阻断；formal 防篡改仍需后续更高层外部信任/发布合同，不能把本 anchor 描述成不可伪造签名。

### F3：predecessor CAS、busy/stale/drift 区分 — PASS

- gateway 读取 account 与 predecessor state digest 后，`persist_operation` 在 `BEGIN IMMEDIATE` 内先执行 full fresh verify，再 exact CAS checkpoint；陈旧 predecessor 返回 `PAPER_BROKER_PREDECESSOR_STALE` 且零写入。
- 双 independent store handle barrier 测试证明同一 predecessor 首次最多一个提交；另一方只可能 stable BUSY/STale，retry 后两个 command、四个 events、两个 orders、两个 positions 和两次现金影响各一次。
- SQLite writer lock 返回 `PAPER_BROKER_BUSY`；CAS stale、semantic conflict 与 identity drift 没有混写。

### session finality 与 source evidence 同事务 — PASS

- `read_evidence_snapshot` 在同一 SQLite read transaction 内 fresh verify 并读取 account/orders/events/checkpoint/finality。
- 独立并发探针在 evidence transaction 建立 snapshot 后提交 EOD：旧读取返回旧 `source_identity + INTRADAY`，下一读取返回新 `source_identity + END_OF_DAY`，输出 `ADVERSARIAL_SOURCE_IDENTITY_AND_FINALITY_SAME_SQLITE_SNAPSHOT_PASS`。
- finality transition 本身在一个 `BEGIN IMMEDIATE` 中写 `session_finality + journal + checkpoint`；非 terminal/UNKNOWN 仍不能 finalize。

## 3. 新增阻断 F4：Windows unclosed store 在解释器退出时泄露 traceback 与绝对路径

### 现象

在 Windows fresh 子进程中初始化并保留一个 `PaperBrokerStore` 到正常解释器退出、刻意不显式调用 `close()`，`PaperBrokerStore.__del__` 调用 `_guard_close()`。此时 `_guard_close()` 才动态 import `ctypes`；Python module teardown 已经开始，稳定抛出 `ModuleNotFoundError`。异常从 `__del__` 逸出并由解释器直接写入 stderr，包含 worktree、生产源码和 Miniforge 的绝对路径及内部调用栈。子进程 exit code 仍为 0，普通 pytest 不会捕获。

精确输出前缀：

```text
LEAVING_STORE_UNCLOSED ...
Exception ignored in: <function PaperBrokerStore.__del__ ...>
Traceback (most recent call last):
  File "F:\\...\\paper_broker_store.py", line 241, in __del__
  ...
ModuleNotFoundError: import of nt halted; None in sys.modules
```

### 根因

`PaperBrokerStore.__del__` 无条件调用可能抛异常的 `close()`；Windows `_guard_close` 在 destructor 时才导入 `ctypes/wintypes` 和解析 `WinDLL`。解释器 teardown 阶段不保证 import system 可用，且 destructor 没有 best-effort exception containment。

### 违反规则

- 任务单 §3.8：所有公开异常稳定脱敏，traceback 不得包含路径、SQL、TOKEN 或 payload；
- 任务单 §10.12 与 §13.3：hostile exception 全回归；
- 通用完成定义要求 shutdown/异常路径不留下未受控泄漏。

### 最小复现

fresh Windows Python 子进程：创建临时 broker/OMS root，调用 `_setup` 等价 public initializer，保持 store 强引用，不调用 `close()`，直接结束进程并捕获 stderr。该复现连续出现上述 traceback/path 泄漏。

### 必须新增测试与通过条件

1. 增加 Windows fresh-subprocess 回归：保留至少一个 open store 到解释器 teardown；stderr 不含 `Traceback`、源码/环境绝对路径或 hostile marker，exit code 为 0。
2. `close()` 仍需显式、幂等并保留当前正常错误处理；`__del__` 只能做不抛异常的 best-effort 资源回收。
3. 不得通过吞掉 public `close()` 的正常失败来修复；只收缩 destructor teardown 路径。若 Windows close API 依赖模块对象，应在正常模块生命周期预绑定调用对象，或在 destructor 内完整 containment。
4. Windows 与 WSL 定向 pytest/Ruff/mypy/fresh import 重新绿色，再由新的独立上下文复验。

## 4. 标准验证结果

Windows 原生 Miniforge，`PYTHONPATH=src`：

- `pytest tests/unit/test_paper_broker_store.py tests/unit/test_paper_durable_gateway.py -q`：`22 passed in 7.46s`；
- Ruff 两个生产文件与两个测试文件：PASS；
- mypy 两个生产文件：PASS；
- fresh import：`WINDOWS_FRESH_IMPORT_PASS`；
- fresh subprocess teardown hostile probe：**FAIL，稳定泄露 traceback/绝对路径**。

WSL Miniforge base，当前 `/mnt/f`：

- 同组 pytest：`22 passed in 5.72s`；
- 同范围 Ruff：PASS；
- 两个生产文件 mypy：PASS；
- fresh import：`WSL_FRESH_IMPORT_PASS`。

平台只读确认：Ubuntu 为 WSL 1，项目路径文件系统为 `drvfs`。这些是 development 工程兼容证据，不是 WSL2/ext4 durability Gate。

`git diff --check` 返回 0；worktree 中存在大量本任务前已有的 M4 脏文件/测试产物，本轮未清理、未覆盖。R2 生产/测试改动仍落在任务白名单；本复验只新增本报告。

## 5. 结论与仍未关闭项

R2 对 R1 F1-F3 的 architecture fix 与双平台开发合同本身成立，但 F4 违反显式 hostile exception/traceback 脱敏不变量，故独立复验结论为 **FAIL**。完成最小 destructor teardown 返工及回归后，需要由未参与返工的新上下文再次独立复验。

本报告不签发 formal policy，不关闭 RUN-0B2/C/D，不创建或注册正式 runner，不启动 28 天 soak。actual WSL2/ext4 power-loss durability、formal policy/risk/loader、scheduler 与 soak 均保持待验，M4 状态仍为 `WAITING_FOR_SOAK_EVIDENCE`。
