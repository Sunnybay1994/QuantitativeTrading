- **现象：** 若 `_flow_bucket` 后续消费者尝试执行 `numeric_pairs.append(...)` 或把它传给要求 `MutableSequence[...]` 的 helper，当前 `Sequence[...]` 应在静态类型检查阶段暴露非法可变消费；若为“消除错误”把注解改回 `list[...]`，则重新隐藏只读契约并回到原 list invariance 缺陷。该反例未被本轮实现者使用。
- **根因：** `numeric_pairs` 在运行时确实由两个 list/alias 提供，但消费者只需单次遍历；把实现容器类型泄露为 mutable list 会同时放宽 API 约束并重新触发协变不成立的问题。
- **应遵循规则：** 保留既有 `Sequence[T_co]` 注解，禁止在该 alias 上 append/extend/复制转换；需要改变生产元素时必须另行修改实际 producer 分支并重新冻结合同，不得在 R10 通过改回可变容器。
- **最小复现：** 在 `src/quant/data/audit_tushare_financials.py:_flow_bucket` 的 `for` 之前加入 `numeric_pairs.append((current, type2, previous))`，或调用参数为 `MutableSequence[...]` 的 helper；静态上应拒绝该消费。将注解改回 `list[...]` 会掩盖这一反例，但违反 §12.6。
- **新增测试/验证节点：** 以 `tests/unit/test_audit_tushare_financials.py::test_flow_and_publisher_bucket_order_is_exact_and_stable` 继续锁 runtime bucket 顺序，并在未来 Validation6 的 mypy production2 阶段保留该负向类型边界；本轮 §12.6 禁止修改 tests2，故不伪造测试或 mypy 已运行。
- **通过条件：** 当前 `Sequence[...]` 唯一注解保持不变，numeric_pairs 只被两处分支赋值及一次迭代消费；非法 append/MutableSequence 需求不能通过静态类型闭合，且 Q1/Q2/Q3/FY 的 runtime 对象、alias、顺序、`None`、operand 与计数不变。当前实现满足，故该反例不形成 P0/P1/P2。

### STATIC_REWORK10 最终判定

`REVIEW_READY / STATIC_REWORK10_REVIEW_PASS`。本轮未发现 P0/P1/P2 或越界写；全部历史 review 保留。PASS 后不得自行 Validation6，且不得把本报告表述为执行验证、真实 audit/snapshot、R3/PIT 或 Gate 已通过。

## FINAL_EVIDENCE_REVIEW_PASS（2026-08-29）

### 最终结论与边界

- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4/REWORK5、STATIC_REWORK6/7/8/9/10 及其全部 P0/P1/P2、STOP、UNRUN 与历史证据均保留，未删除或改写。
- 最终结论：`FINAL_EVIDENCE_REVIEW_PASS`；当前 P0=0、P1=0、P2=0。未发现证据 SHA、边界或 scope 漂移，也未发现越界写。
- 允许的最终边界仅为 `Windows development validation / IMPLEMENTED_PENDING_REAL_AUDIT`。本节不把任何 carrier scope STOP、scope-only 闭包或 delivery 文字提升为真实 audit-v4、snapshot READY、R3/PIT、Linux/WSL Gate 或真实财务数据质量通过。
- 本轮仅做静态文件/证据内容与元数据核对；未运行 Python、pytest、Ruff、mypy、cold、DuckDB/Parquet、真实 data/audit/snapshot、network、stage、commit 或 cleanup。

### 当前 exact7 与 review 写入前绑定

写入前的当前文件哈希/字节数如下；taskbook、roadmap、production2、tests2、delivery 在本轮读取期间保持稳定：

| 文件 | SHA256 | bytes |
|---|---|---:|
| taskbook | `3f14c07f86da3ec547d5dfe13fbd4e763656881b2e111b489326f50c8a3085de` | 67073 |
| roadmap | `ca1ca28cce9355ab75ad52c41c082230dc2951007aba78d2679fc395686acd9f` | 47764 |
| audit production2 | `f1ecadb31060a1f53a99909681808fc0ccae53ea99012d5665b5cc0c7ca776e0` | 80516 |
| publisher production2 | `2dd31a6ed82d8b39f28a7873ee26f2a0e1ef7140acf44c1c4d02fada17dbaee2` | 60065 |
| audit test | `72ccf54ef0cdb824b17041e5bed05aa0c8b7957a4a8d9956114be347578f8f7c` | 94983 |
| publisher test | `8e14cebb1e8b82e92816d29940092d21098f29fde863174c8e27025d2fe50632` | 33300 |
| delivery | `80c087d4e8c6168ca506375ac465bbb709a736c8fe71853ef5ddf9b5e5d9c7c4` | 76176 |
| review（写入前） | `5db38084d506bae3467fd586715487e14c7b3c3de2736b95d830b1f1e10ad68e` | 84866 |

本轮 reviewer 只写入既有 review 文件；所有 evidence/temp/cache 仅读取。V9 的 `01_status_paths.txt` 仍是既有 exact8 路径集合，当前 review 内容变化不改变 status path 集合；未观察到新的 dirty path。

### 中央 grant 与原生 evidence 的逐项核对

1. **Validation6：产品阶段绿色，但不是全绿。**

   taskbook §12.7 与 delivery 同样记录 Validation6 的 Parser、identity、focused2、mypy production2、Ruff exact4、cold 均 PASS；实际 V6 `summary.log` 也逐项记录 `01_identity=0`、`02_focused2=0`、`03_mypy=0`、`04_ruff=0`、`05_cold=0`。关键原生文件 SHA 经静态核对一致：focused2 `3ed6fd346dfc27ee652c412ba643af3d0da21f1402843af29da686c1fa3151bf`/100 bytes，mypy `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2`/44，Ruff `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`/19，cold `f2fa5abb3a94f7638617a512fe5f805721df611e0918049ef9780a23a332da3b`/18，runner `f289fc52c44c43cd6faf290a729de50621261cf6758ad5f8b469b8e5b9d7c493`/9676，summary `ef8b723f5fdf86f83d5c4b08b75a4f1d5b37417e0d52c893c944bde73521320c`/233。

   V6 的 raw status 是含 NUL 终止符的 464-byte stdout；`summary.log` 的最终 STOP 为 PowerShell 5.1 对空尾 record 执行 `Substring(3)` 时的 scope-carrier 异常。因此权威状态只能是 `PRODUCT_GREEN / SCOPE_CARRIER_STOP`，不能改写为 Validation6 全绿。resource finalization 的五个 SHA 也与 taskbook/delivery 原文一致：terminal `722594f855bb9a887c3a9c5416e98a87bbfef79d253ae5d93d400abae4cc1003`、self-restored `b454c9068b3b6c7fd4106f99da44dbb95a60ece0e816b7b8f9d2c8f8ef2d6037`、known-children `edc19edf4c9d775707e2981842dba49711c3dc08f8af5da46b3dd3914d97d100`、python-presence `d950b4e86f37941c3520e2f6072e72fac7dd04015e53cf27644030cfef1c1216`、finalization `e8a04bf0a88930c2a0d5d2e95cf84b0ed16c357615f11c3e4ca7e2571aec9800`。该 finalization 不补写 Validation5 缺失的 `resource_release.log`。

2. **Validation7：过严 cache preflight STOP，不是产品/taskbook 失败。**

   V7 原生 `summary.log` SHA 为 `4d150ae26e6b73ff9d36a7fd38ebd638c57bc5d9b8f0509ad40b779512566a69`，内容为 `STOP:APPROVED_CACHE_NOT_ABSENT`、`PRODUCT_STAGES=NOT_RUN`、`SCOPE_STATUS=UNRUN`；cache preflight 原文记录 `.pytest_cache`、`.ruff_cache`、`.mypy_cache` 存在。taskbook/delivery 均明确 §12.6 没有冻结“worktree 根级 cache 必须不存在”的 absent 条件，因此 V7 只能是 `PREFLIGHT_STOP / SCOPE_NOT_EVALUATED`。cache、V7 evidence root 与这段历史不得被 cleanup 或文档删除后重新包装成产品失败/成功。

3. **Validation8：baseline 可信，status-path return pollution 仍只影响 scope。**

   V8 原生 baseline manifest 为 exact 27 files、2694 bytes，manifest/digest 为 `a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`；实际 pre-manifest 与文档一致。native status stdout 为 464 bytes、SHA `c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`，V8 summary SHA 为 `440706fcafac64f0c15bf525f4e2cef72e1833de80905095664257dc8d849c0d`，原文先有 `CACHE_PRE=PASS`，随后为 `ReadAllBytes` path-format STOP。

   静态读取 V8 runner 可见 `Invoke-GitRaw` 中 `CopyToAsync(...).GetAwaiter().GetResult()` 的非合同返回未被抑制，调用方把 status path 作为多值对象传给 `ReadAllBytes`；V9 runner 改为显式输出路径参数并对非合同返回使用 `[void]`，与 delivery 所述 status-path pipeline pollution 相符。故 V8 权威状态仍为 `CARRIER_STOP / SCOPE_NOT_EVALUATED`，不能被写成产品/taskbook 合同失败，也不能因 V9 修复而删除 V8 历史。

4. **Validation9：仅 scope-only 闭包，无产品重跑。**

   V9 原生 `summary.log` SHA 为 `afabb0b4c30113db062c0462ea51004ae2908583d39412fdc4775e5d694a5c9c`，逐项记录 `CACHE_PRE=PASS`、`STATUS_EXACT8=PASS`、`CACHED_RAW_EMPTY=PASS`、`DIFF_CHECK=PASS`、`ROOTS_RETAINED_IGNORED=PASS`、`PROCESS=PASS;F00_NOT_ACQUIRED`、`CACHE_POST_IDENTICAL=PASS`。pre/post cache manifest 实际均为 2694 bytes、SHA `a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`；raw NUL status 两份均为 464 bytes、SHA `c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`；过滤唯一空尾后的 decoded exact8 path 文件为 448 bytes、SHA `c84195caefbeb1da2e69f6fb04411d8da1b22ebbb97844939b14b474850514cf`；cached raw 为 0 bytes、SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；diff-check stderr 仅既有 LF→CRLF warning、SHA `e38e6f6335acd611aaaec8d8c5be4377785b8855f715218ebf1b176dadf0794b`。

   V9 runner/summary/terminal/process 关键 SHA 也与 delivery/taskbook 原文一致：runner `b025ecb61fccbd75e6faafb10319f207883a471906cc062adfab88d807375a2a`、summary `afabb0b4c30113db062c0462ea51004ae2908583d39412fdc4775e5d694a5c9c`、terminal `c26de83abdc9496cd1301470918ec39ecca1cf389ef0ae1c6504da1800d1c431`、process `8393b61af401a68f4b1beb9ba4b3ea40fdab36213c224b8f9af1af1e605b0031`。V9 evidence root、V1–V6 retained temp roots 与既有 cache 现场均存在；V9 没有 Python、产品测试、audit 或 snapshot 调用。因此 V9 只能证明 baseline-aware scope-only 闭包，不能冒充产品重跑或真实 audit 证据。

### 独立静态对抗反例（实现者未使用；非 P2 发现）

- **现象：** 一个不严谨的最终摘要器若只看到 V6 `01_identity..05_cold=0` 和 V9 多项 `PASS`，就可能把 V6 写成全绿；或把 V7/V8 的 carrier STOP 从 delivery/review 删除；或把 V9 的 scope-only `STATUS_EXACT8/CACHED_RAW_EMPTY/DIFF_CHECK` 写成 product/real-audit PASS。
- **根因：** 混淆阶段 exit code 与完整验证状态，混淆 carrier scope 与产品合同，混淆 scope-only Git/cache 证据与生产代码/真实数据执行证据；删除历史还会破坏可追溯性和 no-clobber 约束。
- **应遵循规则：** 必须同时保留 `Validation6 = PRODUCT_GREEN / SCOPE_CARRIER_STOP`、`Validation7 = PREFLIGHT_STOP / SCOPE_NOT_EVALUATED`、`Validation8 = CARRIER_STOP / SCOPE_NOT_EVALUATED`、`Validation9 = scope-only closure`；V7/V8 evidence/cache 不得删除，V9 不得冠以 product/audit/snapshot 语义，最终边界只能是 Windows development validation / `IMPLEMENTED_PENDING_REAL_AUDIT`。
- **最小复现：** 将 delivery §12.7 的 V6 STOP 行删掉、将 V7/V8 小节删掉，或把 V9 小节的“无 Python、无 0xF00、scope-only”替换为“产品验证通过”；再对照实际 V6 `summary.log`、V8 `terminal.log`、V9 `summary.log` 与各自 runner SHA，即可得到文档—原生 evidence 不一致。
- **新增检查：** 后续 evidence-review/SAFE_COMMIT 前应以固定表逐项比对三种状态字符串、root/summary/runner SHA 与“是否调用产品阶段”字段；本轮只读审查不修改 evidence、cache 或测试，也不伪造该检查已执行为 Validation10。
- **通过条件：** 当前 taskbook、delivery 与本 review 同时保留上述四种边界，关键原生 SHA/bytes 与实际 evidence 相符，V9 cache pre/post 双算一致且 exact8/cached0/diff/roots 证据不漂移；当前满足，故该反例不形成 P0/P1/P2。

### FINAL_EVIDENCE_REVIEW 最终判定

`REVIEW_READY / FINAL_EVIDENCE_REVIEW_PASS`。当前无 P0/P1/P2、无 SHA/boundary/scope 漂移、无越界写；全部历史 review 与 V6–V9 STOP/UNRUN 边界保留。该 PASS 不授权自行 Validation、SAFE_COMMIT 或真实 audit，不代表任何 Gate 通过。
