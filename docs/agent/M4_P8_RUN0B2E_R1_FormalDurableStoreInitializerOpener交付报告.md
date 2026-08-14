# M4 P8 RUN-0B2E R1：Formal Durable Store Initializer / Opener 交付报告

日期：2026-08-12  
角色：内部实现 Agent（用户已暂停新的外部 Agent 调用并允许内部 subagent）  
状态：**实现与 Windows 定向自测完成；不自行宣布 Gate 或主验通过**

## 1. 完成内容

- 新增 `paper_formal_broker_store.py`，提供冻结的三个 public 入口与 process-local capability。
- initialize 实现 cold fresh 四链、独占创建 broker root、旧 cold identity 失效后的 materialized fresh 四链、唯一 B1 store 初始化、最终 fresh 重建与签发。
- open/existing 只从 materialized runtime capability 派生 root、文件名和 OMS 分离路径；existing 保持同一未关闭 store 对象并重新验真全部上游。
- B1 policy descriptor 精确支持 `development` 与 `formal-paper-simulation`；development builder 行为未改变。
- B1 初始化改为 DB no-clobber 创建，并在失败时只清理本次已记录且 identity 未漂移的产物；存在未知/漂移现场时返回 rollback-required 并保留现场。
- formal wrapper 只在 root identity 未漂移且为空时移除 owned root；B1 store 已创建后的失败使用 exact fresh-store 补偿。
- `quant.execution` 使用 lazy export，未把 gateway/service/CLI/soak 引入包冷启动。
- public callable closure 不暴露 `_mint` 或通用 `_token` callable；模块级 assembly 只能产生无效空 attestation，不能通过 existing verifier。

## 2. 修改文件

- `src/quant/execution/paper_formal_broker_store.py`（新增）
- `src/quant/execution/paper_broker_store.py`
- `src/quant/execution/__init__.py`
- `tests/unit/test_paper_formal_broker_store.py`（新增）
- `docs/agent/M4_P8_RUN0B2E_R1_FormalDurableStoreInitializerOpener任务单.md`
- 本报告

未修改 runtime/F0、policy、binding、account、gateway、service、CLI、soak、config、schema/enums、正式 roots/data/journal；未 add/commit/push，未联网。

## 3. 验证证据

显式设置 `PYTHONPATH` 为本 worktree `src` 后执行：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_formal_broker_store.py -q
4 passed in 5.74s

D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_paper_formal_broker_store.py \
  tests/unit/test_paper_broker_store.py -q
15 passed in 12.43s

D:\Miniforge3\python.exe -m ruff check \
  src/quant/execution/paper_broker_store.py \
  src/quant/execution/paper_formal_broker_store.py \
  src/quant/execution/__init__.py \
  tests/unit/test_paper_formal_broker_store.py
All checks passed!

D:\Miniforge3\python.exe -m mypy <同上四文件>
Success: no issues found in 4 source files

cold import + public closure probe
RUN0B2E_COLD_CLOSURE_PASS

git diff --check -- <已跟踪白名单文件>
exit 0（仅既有 Windows LF/CRLF 提示）
```

第一次 focused collection 未显式覆盖宿主 `PYTHONPATH`，错误导入根仓库旧 `costs.py`，因此 collection 失败；确认是路径污染后绑定 worktree `src` 重跑，取得上述明确绿色结果。该次无产品代码执行，不计通过或产品失败证据。

## 4. 覆盖的关键行为

- cold → mkdir → materialized upstream → B1 store → formal capability 正向闭环。
- existing 返回传入同一 capability；fresh open 取得相同 gateway identity。
- capability 字段替换、closed store 均 fail closed。
- formal descriptor 绑定 policy/binding 的版本、cost/fx identity。
- B1 descriptor 写入前故障能精确清空 owned B1 产物，同时保留 caller-owned root。
- formal B1 调用前 hostile 故障只移除本次 owned 空 broker root。

## 5. 限制与后续验收重点

- 按用户当前要求未做 Linux/ext4 Gate；Windows 结果不得表述为正式 Linux Gate。
- Windows focused 使用受控 fresh-verifier 替身签发 exact 类型上游对象，实际文件 I/O、SQLite schema、descriptor、fresh reopen 与 rollback 均走真实 B1；主验仍应以未参与实现者的对抗性复验覆盖真实上游调用次数、TOCTOU、未知并发文件、replacement 和 hostile exception 脱敏。
- 当前未发现必须修改 F0/B2B/B2C/B2D 或扩大到 gateway/service/soak 的合同冲突。
