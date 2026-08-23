# M3 G7D-F0 R3：public Loader Closure 与 Reload 隔离独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的独立复验 Agent  
结论：**PASS（仅表示 R3 独立初验通过；不表示主 Agent 终验、G7/M3 或 Linux ext4 Gate 通过）**

## 1. 独立性、范围与证据边界

- 只读核对了 `AGENTS.md`、`.ai/README.md` 及其直接要求的工程规则、任务单第 11—12 节、R2 独立复验报告、R3 返工交付报告、`src/quant/backtest/a_share_execution.py` 与 `tests/unit/test_m3_formal_a_share_market_facts.py`。
- 生产源码和实现者测试全程只读；唯一写入是本报告。未联网，未写 formal 数据、正式 G1、artifact、journal 或凭据；未执行 `git add`、commit 或 push。
- 本轮新增一个不落盘、实现者未使用的内存 QA：从 loader、构造/分配/序列化入口、repr 和九个 property getter 出发递归遍历 callable closure，并用字节码确认所有可达 callable 中唯一包含 raw `__new__` 分配的函数。
- Windows 使用 `D:\Miniforge3\python.exe`；Linux 兼容验证使用 WSL Miniforge `base`。`findmnt -T .` 返回 `/mnt/f ... drvfs`，**不是 ext4**，故 WSL 证据不能关闭 Linux ext4 Gate。

## 2. R3“标准—证据—结论”映射

1. **可达 callable graph 不再暴露 prepared-facts mint**：源码中签发逻辑已从独立 `mint(identity, selected, provenance)` 移入 `public_loader`。独立探针从 public loader、`__new__`、`__init__`、`__reduce__`、repr 和九个 property getter 递归得到 18 个 callable；没有 callable 参数包含 `identity`、`frames`、`selected` 或 `provenance`。以三个伪 raw prepared 参数调用每个 callable均不能返回对象。**通过**。
2. **唯一可签发 callable 具有完整 public 参数并先 prepare**：独立字节码探针确认，除拒绝式 public `__new__` 外，可达 callable 中唯一执行 `object.__new__` 的是 `load_verified_a_share_market_facts`，其参数集合严格等于 `release`、`plan`、`fresh_context`、`artifact_roots`。源码第 470—476 行先完整调用 `_prepare_verified_a_share_market_facts`，第 477 行才分配对象；prepare 第 538—600 行依次执行 outer 校验、G1 fresh、G7B fresh、八表读取/选择/摘要与 root/file 末次快照。**通过**。
3. **所有对象创建路径与 issued 登记顺序闭合**：public constructor/`__new__` 稳定调用 `reject`；`object.__new__` 只能产生未登记空对象，现有 R2 回归拒绝空对象和完整 slots clone。raw 分配、八帧 clone、slot 写入、HMAC attestation 与 `issued.add` 都是 public loader 的局部语句；`issued.add` 位于 prepare 成功和全部 slot 写入之后，且签发后验证失败会先 discard 再统一拒绝。直接调用 prepare 只返回普通三元组，不能登记伪对象。**通过冻结的 callable-closure 边界**。
4. **R2 内容与持续验证合同未降低**：`verify` 仍按实例身份检查 issued registry，fresh 重算八帧 descriptor/whole-hash，以 process-local key 验证 HMAC；identity、八个 DataFrame property 与 repr 都先经过同一 `consume -> verify`，DataFrame 返回 clone。13 个 slot 漂移、完整 clone、伪 whole-hash、八帧重签、pickle、稳定脱敏异常等 R2 用例继续包含在 23 项 formal suite 并通过。**通过**。
5. **reload 隔离及固定邻接顺序**：reload 反例在 fresh subprocess 内导入支持模块、签发旧 capability、reload 并确认旧 identity/repr 均稳定拒绝；父 pytest 进程不 reload 生产模块。随后按 `reload test -> development facts -> G7B -> G7E` 的固定顺序，Windows 与 WSL base 均为 **26 passed**，未再出现 R2 的 class identity 分裂。**通过**。
6. **R1 八表/窗口/FULL_DAY/reconciliation/lifecycle/limit/benchmark/fresh/物理顺序回归**：23 项 formal facts suite 在双平台全部通过，R1/R2 既有对抗未被删除。**通过当前定向覆盖**。

## 3. 独立新增 QA

实现测试的图根包含 loader、repr 与九个 property getter；本轮额外把 `VerifiedAShareMarketFacts.__new__`、`__init__`、`__reduce__` 纳入根集合，并对递归可达 callable 做两类检查：

1. 参数签名不得接受 prepared facts，伪 `(object(), {}, object())` 调用不得签发；
2. 用 `dis.get_instructions` 搜索 raw `__new__` 分配，确认唯一签发候选是完整四参数 public loader。

Windows 实际结果：

```text
INDEPENDENT_CALLABLE_GRAPH_PASS 18 ['load_verified_a_share_market_facts']
```

该探针未写临时源码或 artifact。它补足了实现测试没有把 constructor/allocation/pickle 入口作为图根的缺口。

## 4. 实际验证结果

### Windows 原生 Miniforge

- `PYTHONPATH=src ... pytest tests/unit/test_m3_formal_a_share_market_facts.py -q`：**23 passed，7320 warnings，22.52s**。
- 固定顺序 reload → development facts → G7B → G7E：**26 passed，12288 warnings，154.21s**。
- Ruff（`a_share_execution.py`、`backtest/__init__.py`、formal facts 测试）：**All checks passed**。
- mypy（两个生产文件）：**Success: no issues found in 2 source files**。
- cold import：**WINDOWS_COLD_IMPORT_PASS**；未加载 Qlib、LightGBM 或 MLflow，初始化 factory 不留 module attribute。
- 独立 callable graph QA：**PASS，18 个 callable，唯一 raw allocation callable 为 public loader**。

### WSL Miniforge base

- 首次命令遗漏 `PYTHONPATH=src`，收集阶段以 `ModuleNotFoundError` 退出，未运行测试；修正命令环境后继续，未把该次尝试误记为产品失败。
- formal facts：**23 passed，7320 warnings，19.09s**。
- 固定顺序 reload → development facts → G7B → G7E：**26 passed，12288 warnings，67.21s**。
- Ruff：**All checks passed**。
- mypy：**Success: no issues found in 2 source files**。
- cold import：**WSL_COLD_IMPORT_PASS**。
- `findmnt`：`/mnt/f F:\ drvfs ...`，明确不是 ext4。

warnings 为既有 Pandera/Polars horizontal concat deprecation 和 `.pytest_cache` 权限告警；未见本轮源码诊断。白名单 `git diff --check` 通过，仅显示 Windows 行尾转换提示。

## 5. 限制与剩余风险

- R3 任务单冻结并由本轮验证的是 public callable closure 图；普通 Python 同进程对非 callable closure cell、函数 `__globals__` 或任意内存对象的恶意反射/monkeypatch 并未被提升为安全隔离边界。R3 交付报告也明确把非 callable closure cell 反射排除在本轮探针外。若后续要声称抵抗任意同进程 Python 攻击者，仍须重新冻结为 native/隔离进程等更强边界，不能把本 PASS 外推为该安全结论。
- WSL 运行于 DrvFS，不是 ext4；真实 formal 数据、正式 G1、真实网络/账户和 Linux ext4 均未触碰或验证。
- 工作树存在大量本任务开始前的其他脏文件/未跟踪报告与临时目录；本轮未修改、清理或据其宣布其他 Gate 状态。

## 6. 最终结论

M3 G7D-F0 R3 在任务单第 12 节冻结的 callable-closure 与 reload 隔离范围内 **独立初验 PASS**。R2 的直接三参数 mint 可达路径已关闭；可达对象分配路径仅剩完整四参数 public loader，且其生产代码顺序为 prepare 完成后才分配、签名并登记；reload 后 development/G7B/G7E 固定顺序在 Windows 与 WSL base 均全绿。

该结论仅允许进入主 Agent 最终验收；不得据此直接把 G7D-F0、G7、M3 或 Linux ext4 Gate 标记为最终通过，也不得把冻结范围外的同进程反射风险表述为已解决。
