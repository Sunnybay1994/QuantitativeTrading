# M3 G8C-C0 R3：配置原路径锚定与全链 Integration 交付报告

日期：2026-08-11  
角色：外部实现 Agent（cursor-grok-4.5-high，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[`M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md`](M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md) §11  
R2：[`M3_G8C_C0_R2_configRelative与G7FR4同步交付报告.md`](M3_G8C_C0_R2_configRelative与G7FR4同步交付报告.md)  
结论：**配置原路径锚定安全缺口已修；unit 反例绿；13 层 public verifier 全链 happy-path 按 §11.2 再次停止并给出精确缺口，未伪造 integration**

## 1. 白名单改动

| 路径 | 说明 |
|---|---|
| `src/quant/research/m3/formal_cli_resolve.py` | 仅修 `_anchor_config_file` + 稳定实体/sha 打开 |
| `tests/unit/test_m3_g8c_c0_formal_cli_resolve.py` | leaf/intermediate link、hardlink、same-bytes、hostile 脱敏与 runtime 前置短路 |
| `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | 唯一 integration：诚实链探针 + §11.2 停止证据（无 happy-path 伪链） |
| 任务单状态 | R3 外部实现已交付 / 待独立初验 |
| 本报告 | 唯一交付报告 |

未改：`m3/__init__.py`、上游 verifier/contracts、`run_m3`、StageRunner、既有 tests/docs。未联网/add/commit。

## 2. §11.1 锚定修复摘要

- `resolve`/`read` 前：自已锚定 `project_root` 起按 `config_relative.parts` **逐 component `lstat` 原路径**；
- 中间 component：exact 目录且非 symlink/junction/reparse；
- leaf：exact 普通文件、非 symlink/reparse、`st_nlink == 1`；
- 随后 `resolve(strict=True)` 只复核 `abspath` 与 resolved 一致且仍在 project root，并再 `lstat` 绑定实体；**不以 resolve 目标检查替代原路径检查**；
- `os.open(..., O_NOFOLLOW)` 稳定读：open 前后 `fstat`/`lstat` 实体 + size 绑定，`sha256` exact=`raw_config_sha256`；
- same-bytes 换 inode / hardlink alias / 链接路径：fail-closed；
- 上述失败均在 `compute_m3_runtime_identity` 与任一 artifact verifier 前发生；`FormalCliResolveError` 清空 cause/context，消息无绝对 path/hash/TOKEN；零写。

## 3. 验证证据

| 平台 | 命令 | 结果 |
|---|---|---|
| Windows Miniforge | focused unit+integration pytest | **17 passed, 2 skipped** |
| Windows | Ruff / mypy（白名单 3 文件） | PASS / Success: 3 files |
| Windows | cold import（无新增 mlflow/qlib/lightgbm） | PASS |
| WSL base / DrvFS | focused unit+integration | **18 passed, 1 skipped** |
| WSL base | Ruff / mypy / cold | PASS |

Skip 说明：

- Windows unit：`test_rejects_leaf_symlink_before_runtime` — 宿主无 leaf symlink/`mklink` 权限（中间 junction 与 hardlink/same-bytes/hostile 已覆盖）；WSL 上该 leaf symlink 用例 **PASS**。
- 双平台 integration：`test_r3_stop_no_honest_public_formal_chain_for_resolver` — §11.2 停止（见下）；断言缺口后 `pytest.skip`，**不宣称 13 verifier happy-path**。

（WSL1/DrvFS 仅兼容证据，非 ext4 Gate。）

## 4. §11.2 Integration 停止：精确缺口

### 现象
批准的唯一 integration 文件无法在不违反禁止项的前提下覆盖「13 层 public verifier 各 exact once/order + resolution 可绑定 `run_formal_backtest_stage`」。

### 根因 / 精确证据
1. `data/clean/m3_g1/releases` **不存在**；无已发布 formal G1 release 树。
2. `tests/fixtures/` 仅有 CSV/`m3` 样本，**无** `backtest_plan` / `snapshot-requests` 等 G8 stage 具名闭包。
3. 既有可复用“支持”均命中 §11.2 禁止项：
   - `tests/unit/test_m3_g7f_formal_backtest_artifact.py`：`monkeypatch.setattr` 生产 verifier、`object.__setattr__`、`SimpleNamespace`、`replace` verified；
   - `tests/unit/test_m3_g8_r1_formal_backtest_stage.py`：同上；
   - `tests/integration/test_m3_g8_r1_formal_backtest_stage_golden.py`：依赖上述 unit support + monkeypatch verifier。
4. 复制/改编完整 G1→backtest_plan 实体闭包将构成「千行伪 formal 链」。

### 应遵循规则
任务单 §11.2：只允许复用诚实 public formal 链；禁止 monkeypatch verifier、`object.__new__`/`replace` verified、SimpleNamespace、私有 issuer、千行伪链；若仍无诚实链，停止给精确证据，不迁就。

### 本轮处置
- 新增 `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` 仅作缺口探针与签名可绑定性静态核对，然后 skip；
- **未**实现伪造 happy-path；**未**宣称 13 verifier once/order 已覆盖。

## 5. 未决 / 非声明

- 未宣称独立初验、主验、G8C-C0 工程合同 PASS、Gate/ext4、C1 解锁
- 13 层 public 全链 happy-path 仍阻塞于诚实 formal 产物来源；需主 Agent 另冻真实 fixture/产物或放宽白名单后才能继续

## 6. 下一步

1. 全新外部独立初验 → 唯一报告：`docs/agent/M3_G8C_C0_R3_配置原路径锚定与全链Integration独立复验报告.md`
2. 主 Agent 复核锚定合同与 integration 停止证据；决定是否另供诚实 formal 链或改合同
