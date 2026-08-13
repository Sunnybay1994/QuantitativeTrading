# M3 G8C-C0 F0：诚实 Formal Chain Fixture 可行性审计报告

日期：2026-08-11  
角色：外部只读设计审计 Agent（cursor-grok-4.5-high，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
权威合同：[`M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md`](M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md) §11；R3 交付：[`M3_G8C_C0_R3_配置原路径锚定与全链Integration交付报告.md`](M3_G8C_C0_R3_配置原路径锚定与全链Integration交付报告.md)  
范围：**只读** production / tests / config / data；**仅新增本报告**；不实现、不联网、不 add/commit。  
结论：**默认推荐 B（session-scope 公共 builder support）+ 窄 C（环境门控可选冒烟）；纯 A 在当前 dirty 工作树上运营阻断；纯 D 不能替代 13 verifier happy-path。** 在「双平台默认绿且无 pyqlib 元数据 / 禁止任何 data 写入 / 禁止扩白名单 support」任一硬约束下，诚实全链 **BLOCK**。

---

## 1. 审计问题与硬约束

R3 §11.2 仍缺：integration 上对 `resolve_formal_backtest_cli_inputs` 证明 **13 层 public verifier 各 exact once 且顺序正确**，resolution 可绑定 `run_formal_backtest_stage`（不真跑）。必须满足：

- 不 monkeypatch verifier / 私有 issuer / `object.__new__` / `replace` verified / `SimpleNamespace`
- 不复制千行伪链；不把正式 `data/` 当普通自动测试依赖；不伪造 G1 receipt
- 13 verifier 顺序可诚实证明；双平台**可运行**；维护体量最小

本审计比较四案：A 留存真实 public publish bytes；B session-scope public builder；C 环境门控读用户已有正式 artifacts；D 拆 resolver（纯路径计划 + fresh 验证）。

---

## 2. 现场证据（只读探针）

### 2.1 工作树与根项目产物

| 位置 | 发现 |
|---|---|
| 工作树 `data/clean/m3_g1/releases` | **不存在**（与 R3 stop 一致） |
| `tests/fixtures/` | 仅 CSV/`m3` 样本；**无** `backtest_plan` / `snapshot-requests` |
| 根项目 `data/clean/m3_g1/releases/` | **2** 个真实 formal G1：`08eb9b31…`（≈44MB / **18** 文件）、`3c9bda84…`（≈43MB / 18 文件）；根目录 **无** `receipt.json` |
| 根/工作树 stage 树 | **无**完整 `G1→…→backtest_plan` 具名闭包；仅见残缺 snapshot 试验树（如 `m3-g2a/.../formal_g2a_windows`：snapshot-temp ≈60MB / 629 文件，无 work/backtest_plan） |
| `tests/support/` | **无**可复用 formal-chain support 包 |
| 既有 G4–G8 formal unit/golden | 普遍 `monkeypatch` verifier、`SimpleNamespace` / `object.__setattr__`、伪造 `code_version`（如 `g4b-formal-fixture-v1`）——命中 §11.2 禁止项 |

G1 文件集合（权威 18 项，与 `verify_g1_release` `_FINAL_ENTRY_NAMES` 合同一致）：`manifest.json`、`quality.json`、`cross_source_reconciliation.json|.parquet`、八表+CA/涨跌停等 parquet。`bar_1d.parquet`≈27.9MB，`price_limit_1d.parquet`≈10.5MB，`manifest.json`≈2.1MB。

### 2.2 Resolver 对「诚实链」的真实耦合

`formal_cli_resolve._resolve` 成功路径（摘要）：

1. 锚定 `configs/...` 原路径 → `compute_m3_runtime_identity(..., frozen_config_digests=...)`  
2. 用 **当前** `runtime.code_version` 重算 `snapshot_request_key`，并与磁盘 request **逐字段**比对（含 `code_version`）  
3. `verify_g1_release`（`data/clean/m3_g1/releases/<id>`，无 G1 receipt）  
4. 再按序：snapshot → provider → provider-validation → experiment → label → folds → feature → alignment → model → prediction → target → backtest_plan（共 **13**）  
5. `build_provider_runtime_fingerprint()` **无条件**参与 `provider_key` / validation_key 派生  
6. `compute_experiment_key(..., dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256)` —— **平台进入 identity**

因此：留存 bytes 只有在 **当前 runtime identity 与发布时 exact 一致** 时，才能仅靠 public verify 恢复 resolver 所需 capability；否则在 bootstrap request 或后续 key 派生处 fail-closed。

### 2.3 Identity / 依赖门闩（本机实测）

Windows Miniforge（工作树）：

- `code_source=git`，**`DIRTY=True`**
- `code_version` 形如 `m3-git-v1-<commit>-dirty-<dirty_sha>`（dirty 绑定 `status_sha256` + `source_tree_sha256` + `pyproject_sha256`）
- `os=nt/win32/Windows` → `dependency_fingerprint` 与 Linux **必然不同** → 自 experiment 起整链 key 不可跨平台共用一份 stage 树
- `qlib`：**未安装**；`lightgbm`：有
- `build_provider_runtime_fingerprint()` 需要 `importlib.metadata.version` 于 `fire,loguru,numpy,pandas,pyarrow,pyqlib,tqdm` —— 本机缺 `fire` 时 **直接抛 `PackageNotFoundError`**（resolver 未特判该异常为 exit 4；会落入闭包失败语义）

WSL：

- `base`（3.13）：`qlib=None`，`fire=None`，`lightgbm` 有  
- `py312`：`qlib` / `lightgbm` / `fire` **均有**（与 G0 Qlib 隔离环境一致）

### 2.4 Public verify 能否从留存 bytes 恢复 exact capabilities？

| 层 | 仅 public verify？ | 受 dirty/runtime 影响？ |
|---|---|---|
| G1 `VerifiedG1Release` | **能**（`G1Release` 路径 + `verify_g1_release`；无 receipt） | 否（纯磁盘闭包） |
| snapshot…provider-validation | **能**（若 receipt/artifact/request 齐全） | **是**：`code_version` + provider package fingerprint 必须与**当前进程**一致才能被 resolver 找到并验收 |
| experiment…backtest_plan | **能**（同上） | **是**：另加 `dependency_fingerprint`（含 OS/machine） |
| resolver 返回的 verified 对象图 | **能**（resolver 本身就是「只 verify、零写」） | 同上；另需 `configs/` 下真实配置文件与 `raw_config_sha256` 锚定 |

**不需要**私有 issuer 做 verify。`publish_stage_receipt` 是 public API（`run_state` / `m3.__init__` 导出），只在 **构造**链时需要；resolver 消费路径只用 verify。

伪造 G1 receipt：**不需要也不允许**——与 G7A/B/F R3 合同及现场真实 release 布局一致。

---

## 3. 四案比较（证据导向）

### A. 留存一次真实 public publish 的只读 fixture bytes

**做法**：主 Agent/专人在干净树用 public builder 发布完整 `G1+stage→backtest_plan`，把 bytes 固化到 gitignored 或外部盘；integration 只 copy/read + resolver。

| 维度 | 评定 |
|---|---|
| 诚实性 | 高（若发布时未 monkeypatch） |
| 维护体量 | 低代码 / **高字节与失效成本** |
| 双平台 | **一份树不够**（experiment+ 平台绑定）；需 Win+Linux 各一份或每平台现场发布 |
| Dirty | **当前分支 DIRTY=True → 任一源码/状态变更即改 `code_version` → request key 漂移 → 整链失效** |
| 体积 | 真实 G1 单份 ≈44MB/18 文件；完整 stage 未见成品，下限参考残缺 snapshot≈60MB， realistically **≫100MB**；不宜进 Git（且 `artifacts/*`、`data/clean/*` 已 ignore） |
| 正式 data 依赖 | 若把根项目 `data/clean/m3_g1` 当默认 fixture → **违反**「不把正式 data 当普通自动测试依赖」 |
| 现状 | **无可复用完整链**；仅有 G1 |

**裁决**：**不适合作为默认 CI/开发反馈环方案**。仅可作「冻结 tag + clean tree + 双平台各一份 + 显式门控」的可选金样；在本 dirty 工作树上 **运营阻断**。

### B. Session-scope public builder support

**做法**：新增测试 support（非 production）：同一 pytest session 内用 **public** `publish_g1_release` / `build_*_artifact` / `publish_stage_receipt` /（必要时）StageRunner，写入 **gitignored** 路径（`data/clean/m3_g1/releases/<id>` + `artifacts/research/m3/...` 或专用 config `artifact_root`），`code_version`/`dependency_fingerprint`/`provider_runtime_fingerprint` 全部取 **当前** `compute_m3_runtime_identity` / `build_provider_runtime_fingerprint`；随后 integration **只调 resolver**（零写断言），用 wrap/spy **计数** 13 个 public verifier（允许 patch **调用计数器包一层**，但 **不得替换** verifier 语义 —— 更稳妥：在 support 外用 `unittest.mock` 的 wrap，或解析调用日志；禁止把 fake 实现装回去）。

| 维度 | 评定 |
|---|---|
| 诚实性 | **最高**：与 dirty/runtime 自洽；无伪 code_version；G1 可用合成 inputs 的 public publish（`test_m3_formal_feature_artifact._verified_g1` 已示范 public publish+verify，但后续伪造 code_version —— B 必须删掉该伪造） |
| 维护体量 | **中**：一份链式 support ≈编排 13 builder，远小于手写千行 parquet 伪链；合同变更时随 public API 修 |
| 双平台 | **可运行**：每平台各自 session 构建（自然满足 dependency_fingerprint）；缺 pyqlib 元数据/Qlib 的平台 **显式 skip**，不算伪绿 |
| 正式 data | **不读**用户根 G1；合成 release 写入 ignore 路径，session 结束清理 |
| 风险 | 需扩测试白名单；builder 链依赖 dump/feature worker/LightGBM；Windows/base 可能无法完整构建 |

**裁决**：**默认推荐**。这是唯一在 dirty 树上仍能稳定证明「resolver 调真 verifier」的最小维护路径。

### C. 环境门控读取用户已有正式 artifacts

**做法**：`QUANT_M3_FORMAL_CHAIN_ROOT` / `QUANT_M3_G1_RELEASE_ID` + snapshot_id/fold/horizon；未设置则 skip；设置则只读 resolve。

| 维度 | 评定 |
|---|---|
| 诚实性 | 高（用户真实产物） |
| 维护体量 | 极低 |
| 现状 | 用户 **仅有 G1，无 backtest_plan 闭包** → 今天 **无法点亮** happy-path |
| 正式 data | 门控可选 → **符合**「非普通自动依赖」；默认测试不碰 |
| Dirty | 与 A 相同：用户树必须与**当前** code_version/dep_fp 匹配 |

**裁决**：**推荐作 B 的可选补充冒烟**，不能单独关闭 R3 缺口。

### D. 拆 resolver：纯路径计划 + fresh 验证分层

**做法**：生产侧拆 `plan_formal_backtest_cli_paths`（纯 key/path）与 `verify_formal_backtest_cli_closure`（13 verifier）。

| 维度 | 评定 |
|---|---|
| 对 13 verifier happy-path | **不消除**对诚实链的需求；只让 unit 更易测路径派生 |
| 白名单 | 改 production API → **超出** C0/R3 白名单，需主 Agent 重冻 |
| 风险 | 若用分层借口在 unit 用假 capability「拼」resolution → 直接违反合同 |

**裁决**：**可列为后续可维护性重构候选项，不是 F0 fixture 解法**；不能替代 §11.2。

---

## 4. 方案矩阵（压缩）

| 案 | 13 verifier 可证？ | Dirty 可活？ | 双平台 | 维护 | 正式 data | 推荐 |
|---|---|---|---|---|---|---|
| A 留存 bytes | 仅 identity 冻结时 | **否（本树）** | 需双份 | 字节重 | 易违规 | 否（可选金样） |
| **B session builder** | **是** | **是** | 分平台构建+门控 skip | 中（最小诚实） | 不依赖 | **是** |
| C env 门控 | 有完整树时是 | 同 A | 同 A | 低 | 门控 OK | 辅 |
| D 拆分 API | 否（缺链仍缺） | n/a | n/a | 降生产复杂度 | n/a | 非本缺口 |

---

## 5. 推荐包拆分 / 白名单 / API / fixture 格式

### 5.1 推荐包拆分（最小）

主 Agent 另冻 **F0/R4** 白名单（C0 生产代码不再动）：

1. `tests/support/m3_formal_public_chain/`（新建）  
   - `publish_mini_formal_g1.py` — 仅 `publish_g1_release` + `verify_g1_release`（合成 inputs；可复用 G1 unit 的 public/fixture inputs，**禁止**改 production）  
   - `publish_formal_stage_to_backtest_plan.py` — 按 resolver 同序调用 public `build_*` + `publish_stage_receipt`；**强制** `code_version=runtime.code_version`  
   - `session_fixture.py` — `pytest` session-scoped：构建 → yield `FormalChainLocator` → 尽力清理  
2. `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` — 删除「永久 stop skip」为主路径；改为：无门控依赖则走 B fixture；另保留 C 门控用例（可选）  
3. 唯一任务单/交付/初验报告（由主 Agent 冻结）  

**禁止**再改：`formal_cli_resolve.py`（除非另发现生产 bug）、G1–G7 verifier、把根 `data/clean/m3_g1` 链进默认 pytest。

### 5.2 `FormalChainLocator`（建议 fixture 格式）

```python
@dataclass(frozen=True)
class FormalChainLocator:
    project_root: Path                 # 真实工作树 root（含 src/quant）
    config_relative: PurePosixPath     # configs/... 普通文件
    snapshot_id: str                   # hex64
    fold: str                          # fold_000
    horizon: int                       # 5|10
    g1_release_id: str
    stage_root: Path                   # 已存在真实目录
    # 仅诊断：构建时冻结的 code_version / dep_fp / provider_fp（测试断言用，不传给 resolver）
```

磁盘布局必须与生产具名合同一致（禁 `common/` alias 布局）：

- `data/clean/m3_g1/releases/<g1_release_id>/`（18 文件，无 receipt）  
- `artifacts/research/m3/`（或专用 ignore 下 artifact_root）下：`snapshots/`、`snapshot-requests/`、`providers/`、`provider-validations/`、`runs/`、`labels/`、`folds/`、`features/`、`work/<work_key>/{alignment,train,predictions,targets,backtest_plan}/`、`receipts/<stage>/...`  
- `data/external/qlib/v0.9.7/dump_bin.py` 已存在即可复用（工作树已有）

### 5.3 Integration 断言要点

- `resolve_formal_backtest_cli_inputs(...)` 成功；前后 stage/G1 **零写**  
- 13 verifier **各一次、顺序**与任务 §4 一致（wrap 计数，不替换实现）  
- `FormalBacktestCliResolution` 字段可 `inspect.signature(run_formal_backtest_stage)` 绑定；**不调用** StageRunner  
- 平台门控：`build_provider_runtime_fingerprint` 或 Qlib/LightGBM 不可用 → `pytest.skip` 并写明环境（Windows/base vs py312）

### 5.4 停止条件（实现期必须再停）

1. 任一 stage 只能靠 monkeypatch verifier / SimpleNamespace / replace verified / 私有 helper 才能过  
2. 需要伪造 `code_version` 或手写大型 parquet 闭包  
3. 默认测试开始硬依赖根项目正式 G1/stage  
4. 为过双平台而安装/污染 `base` 或跳过 WSL 合同  
5. 支持模块演变成第二套 orchestration SSOT（应调用 public builder，不复制规则）

### 5.5 反例（独立初验应加）

- 构建后改动无关源文件使 dirty hash 变 → 旧 session 树不可被新进程 resolver 接受（证明 A 脆弱）  
- 把 Win 树拷到 WSL（或反之）→ experiment_key 漂移 fail-closed  
- 删除 `backtest_plan` receipt → resolver exit 5，且 13 次调用在 plan 前停止  
- same-bytes 换 G1 root inode → fail-closed  
- 未设置 C 门控且强制禁用 B → 必须 skip/停，不得伪绿  

---

## 6. 阻断声明（何时宣布不可行）

在不放宽合同的前提下，若主 Agent 同时要求下列任一组，则诚实 13 层 happy-path **BLOCK**：

1. **禁止**新增 `tests/support/**` 且 **禁止** session 写入 gitignored `data/clean`/`artifacts`；又 **无**可门控完整正式链（现状）  
2. 要求 **Windows Miniforge base 与 WSL base 均默认跑通** full builder/verify，但不允许使用 `py312`、也不安装 `pyqlib/fire/...` 元数据 —— 与 `build_provider_runtime_fingerprint` / Qlib 现实冲突  
3. 坚持 **纯 A 进仓库字节** 且开发树保持长期 dirty  

此时应保持 R3 integration 的精确 stop，**不得**用 G7F/G8 monkeypatch support 冒充通过。

---

## 7. 给主 Agent 的最小决策建议

1. **采纳 B 为主**冻结 F0 任务单（扩测试白名单 + session public chain support + 改唯一 integration）。  
2. **附带 C**：文档化 env 门控，供用户自有完整链冒烟；今日无链则跳过。  
3. **拒绝**把根 G1 拷进默认 fixture；**拒绝**纯 D 代替本缺口。  
4. 双平台语义写死为：**可运行 = 有依赖则测、无依赖则显式 skip**；完整绿优先 **WSL `py312`**（与 G0 一致），Windows 作反馈环/skip。  
5. 若需长期金样，另开 **clean tag** 流程做 A，且每平台一份、版本钉死 —— 不作为 C0 日常闭环。

---

## 8. 非声明

- 未实现任何代码；未改 production/tests（除本报告）  
- 未宣称 R3 初验/主验、G8C-C0、Gate/ext4 PASS  
- 未完整跑通 `verify_g1_release` 墙钟（真实 44MB release 在 DrvFS 上 verify 成本高；文件集合/无 receipt/路径证据已足够支撑本设计结论）
