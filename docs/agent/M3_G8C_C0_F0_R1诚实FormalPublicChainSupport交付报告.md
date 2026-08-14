# M3 G8C-C0 F0 R1：诚实 Formal Public Chain Support 交付报告

日期：2026-08-11  
角色：外部 C0-F0 实现 Agent（cursor-grok-4.5-high，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`（WSL 路径挂载为 DrvFS）  
任务单：[`M3_G8C_C0_F0_R1诚实FormalPublicChainSupport任务单.md`](M3_G8C_C0_F0_R1诚实FormalPublicChainSupport任务单.md)  
可行性审计：[`M3_G8C_C0_F0_诚实FormalChainFixture可行性审计报告.md`](M3_G8C_C0_F0_诚实FormalChainFixture可行性审计报告.md)  
结论：**按 §8 停止条件立即停写；未新增 `tests/support/m3_formal_public_chain/`，未改 integration；不宣称 F0/C0/C1/Gate PASS**

---

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `tests/support/m3_formal_public_chain/**` | **未创建**（命中停止条件） |
| `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | **未改**（永久 stop skip 仍保留） |
| 任务单状态 | 更新为「外部实现已停止…」 |
| 本交付报告 | 新增（唯一代码外交付物） |

未改：production、config、既有 unit/G1–G8 tests、正式 data/artifacts。未联网、未 add/commit。

---

## 2. 可行性核验（写代码前）

### 2.1 环境门控探针

| 环境 | `platform_supports_renameat2_noreplace` | `build_provider_runtime_fingerprint` | 其它 |
|---|---|---|---|
| Windows Miniforge | **True**（MoveFileEx） | **PackageNotFoundError: fire**（pyqlib 亦缺） | 按任务须在任何 G1/stage 写入前 **窄 skip** |
| WSL `base` | **False**（DrvFS） | **PackageNotFoundError: fire**（pyqlib 缺） | 同上，写入前 skip |
| WSL `py312` | **False**（DrvFS） | **OK**（`43d70d7e…`）；fire/pyqlib/lightgbm 齐全 | 依赖自洽，但 **G1 public publish FS 阻断** |

文件系统：`df -T` → `F:\` / `drvfs` 挂载于工作树（非 ext4）。

Owned 探针目录 `artifacts/research/m3/_f0_rename_probe`：直接调用 `_renameat2_noreplace` → **`G1_RELEASE_PUBLISH_UNSUPPORTED`**；随后 owned-only 删除，路径不残留。

### 2.2 硬阻断：G1 层只能靠禁止项

现象：任务要求 WSL `py312` **actual** 用 production public `publish_g1_release` 构造正式 G1 树（18 文件、无 receipt）。

根因：

1. `publish_g1_release` 终态提交走 `m3_release._renameat2_noreplace`（`src/quant/data/m3_release.py` ≈1181）。
2. 本工作树在 WSL 上为 **DrvFS**；`platform_supports_renameat2_noreplace() is False`；同路径直接 rename 得 `G1_RELEASE_PUBLISH_UNSUPPORTED`。
3. 既有 G1 unit 在不支持主机上用 **`monkeypatch.setattr(release_mod, "_renameat2_noreplace", …)`**（`test_m3_g1_release.publish_capable`）才能 publish——这是**私有 helper** 注入。
4. 任务 §4/§8：**禁止私有 helper monkeypatch**；禁止伪造 verified / 正式 data / 长期留存 bytes。

应遵循规则：§8「任一 public 层只能靠…私有 helper…才能通过 → 立即停止，不扩白名单、不迁就」。

最小复现（WSL py312，工作树根）：

```text
platform_supports_renameat2_noreplace() -> False
_renameat2_noreplace(src, dst) -> M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED")
# 因而 publish_g1_release 在 commit 步无法取得正式 final release 目录
```

通过条件（需主 Agent 重冻其一，本 Agent 不擅自扩权）：

- 在 **ext4/native** 工作树上跑 F0（`renameat2` True），或  
- 显式批准测试侧对 publish commit 的**公共**兼容边界（非私有 `_renameat2_noreplace` monkeypatch），或  
- 放宽/改写 G1 发布合同使 DrvFS 上存在诚实 public 路径。

### 2.3 次级风险（未堆代码，仅记录）

- **行数**：既有 `test_m3_formal_feature_artifact` 仅到 feature 且含伪 `code_version` 已约 450 行；具名布局下再加 provider-validation/label/alignment/model/prediction/target/backtest_plan + session/cleanup/门控，诚实 public 编排**极易突破 600 行/三 support 文件**上限。未尝试硬塞。
- **跨测耦合**：G1 raw fixture 在 `test_m3_g1_release.py`（≈1399 行）；任务允许复用 raw inputs，但若整文件 importlib 拖入仍属高耦合；复制则超行数。因 G1 publish 已阻断，未展开。
- **Windows/base**：`fire`/`pyqlib` 缺失 → 符合「写入前窄 skip」；**不能**用 Win 绿代替 WSL py312 actual。
- **3600s**：未启动全链 build；在 G1 层已无法终态，无需耗尽会话时钟。

---

## 3. 验证命令与结果

| 检查 | 结果 |
|---|---|
| Windows / WSL base 依赖门控探针 | PASS（证据：缺 fire → 应 skip；未写 G1/stage） |
| WSL py312 provider fingerprint | PASS |
| WSL py312 `renameat2` / 直接 commit | **FAIL → 合同停止**（`supports False` / `G1_RELEASE_PUBLISH_UNSUPPORTED`） |
| WSL py312 actual public chain + resolver | **未跑**（停止条件已触发） |
| Ruff / mypy / cold import | **N/A**（无新增/修改 `.py` 测试或 support） |
| diff | 仅任务单状态 + 本报告；无 production/tests 代码 diff |

探针临时文件（`.tmp-g8c-c0-f0-*.py`）为会话私有，可删；不纳入交付。

---

## 4. 反例与禁止项自检

| 项 | 本轮 |
|---|---|
| monkeypatch / wrap verifier | 未做 |
| verified 伪造 / SimpleNamespace / private issuer | 未做 |
| 固定 code/dependency/provider identity | 未做 |
| 读根项目正式 data / 长期 bytes | 未做 |
| 联网 / MLflow / 改 production/config/既有 tests | 未做 |
| 为过 DrvFS 而 patch `_renameat2_noreplace` | **拒绝**（停止原因） |

---

## 5. 非声明

- **不**宣称 F0「诚实 public chain test support 工程合同 PASS」
- **不**宣称 C0 integration / C1 / Gate / ext4 PASS
- 未替换 R3 integration 永久 stop skip；13 verifier once/order 仍未覆盖

---

## 6. 给主 Agent

1. 复核：DrvFS 工作树 + 禁止私有 rename helper ⇒ WSL py312 无法诚实 `publish_g1_release`。
2. 重冻路径建议优先：**ext4 工作树**上重跑 F0；其次才是公共 publish 兼容 API（非私有 monkeypatch）。
3. 行数/三文件上限建议在重冻时按 13 层具名 receipt 编排重新估，避免再次逼近 600 硬顶。
4. 独立初验：本轮无 support 可验；若主 Agent 接受停止证据，初验应核对「未堆伪链、未改 production」。
