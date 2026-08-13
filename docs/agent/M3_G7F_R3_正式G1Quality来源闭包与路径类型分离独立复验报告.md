# M3 G7F R3：正式 G1 Quality 来源闭包与路径类型分离独立复验报告

日期：2026-08-10  
角色：未参与实现的全新外部独立初验 Agent（只读生产/实现测试/任务单/既有报告；本文件为唯一写入）  
任务单：[`M3_G7F_R1正式A股三场景回测Artifact任务单.md`](M3_G7F_R1正式A股三场景回测Artifact任务单.md) §17  
交付报告：[`M3_G7F_R3_正式G1Quality来源闭包与路径类型分离交付报告.md`](M3_G7F_R3_正式G1Quality来源闭包与路径类型分离交付报告.md)

## 结论

**FAIL（不得解锁主验/G8 同步返工）**。主验复核补充探针证明：在 **exact** `G1Release` + exact `VerifiedG1Release`（`dataclasses.replace`，无 SimpleNamespace）指向 same-bytes 拷贝 root 时，`verify_backtest_build_output` 仍通过，违反 §17.2.5 / §17.3「拒绝 root replacement」与 pre-final/verifier 共享闭包。不得宣 Gate。

## 逐项核对

| 合同项 | 证据 | 结果 |
|---|---|---|
| formal 三路径 exact 类型 | `FormalBacktestArtifactUpstreamPaths` 仅三 `Path`；fresh context `type is` 绑定；安全导出 | PASS |
| development 四路径不变 | 仍含 `g1_receipt_path`；development `receipt.json`+`receipt_sha256`；dev reporting 绿 | PASS |
| formal 21-input manifest→quality→八表 | 固定 21；`[12]=quality.json`；禁假 receipt；samefile 拒 alias | PASS |
| quality path/sha 派生 | `_formal_g1_quality_path` + `quality_sha256`；无 G7A/G7B 私有 import | PASS |
| public helper / pre-final / verifier 共享闭包 + 拒 root replacement | helper/final+receipt 可拒路径发散；**pre-final 对 exact same-bytes copied root 仍通过**（主验补充 S2） | **FAIL** |
| 白名单 / 禁改 G8 | 初验只写本报告；未改生产/实现测试；未联网/add/commit | PASS* |

\*工作树另有既有脏文件，不在本包主张范围。

## 实现者未用对抗（双平台）

独立脚本：`.tmp-g7f-r3-indep-adversarial.py`（证据 `.tmp-g7f-r3-indep-adv-win.txt` / `.tmp-g7f-r3-indep-adv-wsl.txt`）。

| ID | 攻击面 | Win | WSL |
|---|---|---|---|
| A1a–e | formal/dev/subclass/duck 混配零读取；forged context→public helper | PASS reject | PASS |
| A2a–b | quality↔experiment / trade_calendar hardlink | PASS reject | PASS |
| A3 | 伪 receipt + 29 outputs 合法重签后 verify | PASS reject | PASS |
| A4a–b | same-bytes root 替换后 verify reject + helper 路径发散 | PASS | PASS |
| A4c（初版） | pre-final；**当时用 SimpleNamespace nested，证据不足** | 见主验补充 | — |
| A5 | hostile `_file_sha` 脱敏 | PASS | PASS |

## 定向验证证据（初验套件，未因本补充重跑）

Windows：G7F `11 passed`；邻接排除 G8 `128 passed`；R2 fixed-order `4 passed`；dev `10 passed`；Ruff/mypy/cold/diff 绿。  
WSL base（`wslfs`/DrvFS）：G7F `11`；邻接 `128`；R2 `4`；Ruff/mypy/cold 绿。

## 主验补充（A4c exact 复核，窄探针未重跑全套）

脚本：`.tmp-g7f-r3-a4c-supplement.py`；证据：`.tmp-g7f-r3-a4c-supp-win.txt`（Win，238.8s）。

| ID | 做法 | 结果 |
|---|---|---|
| SETUP | `_formal_case` + `build_backtest_artifact` 一次合法 tree | OK |
| S1 | `object.__setattr__(release,"release",SimpleNamespace(...))` 后 `verify_backtest_build_output` | **UNEXPECTED_PASS**（G7F 层无 `type(release.release) is G1Release`；fixture mock 掉 F0 nested guard） |
| S2 | `G1Release(release_id=rid, root=copied/<rid>, ...)` + `dataclasses.replace(VerifiedG1Release, release=..., artifact_paths=remapped, quality_sha256=旧)`；`type` exact；same-bytes；再 `verify_backtest_build_output(good_tree)` | construct OK；**UNEXPECTED_PASS** |

原 A4c「CONTENT_PASS_NO_RECEIPT_LOCK」不能再当作无害残留：非 exact nested 使边界不清；exact 构造后 pre-final 仍接受 copied root，构成 §17 合同 FAIL。

## FAIL 闭环与最小返工

1. **现象**：已生成合法 G7F tree 上，将 `kwargs["release"]` 换成指向 same-bytes 拷贝 root 的 exact `VerifiedG1Release`/`G1Release` 后，`verify_backtest_build_output` 返回成功；另：仅 SimpleNamespace nested 亦未被 G7F pre-final 拒绝。  
2. **根因**：G7F `_validate_formal_input_identity` 只 exact 外层 `VerifiedG1Release`，不强制 nested `G1Release`；pre-final 闭包以 `root/quality.json` 名 + `quality_sha256`（及后续 mock/内容重建）验收，未把「构建时 G1 root 物理身份 / 已写 tree 所绑定来源 root」钉死，故 same-bytes root replacement 在无 receipt 路径下逃逸。  
3. **应遵循规则**：§17.2.5（identity/pre-final/verifier 共享闭包；拒 root replacement）；§17.3（same-bytes G1 whole-root replacement 必须 fail closed）。  
4. **最小复现**：`.tmp-g7f-r3-a4c-supplement.py` → `S2_exact_copied_root_prefinal:UNEXPECTED_PASS`（及 S1）。  
5. **新增测试（实现者）**：  
   - exact `G1Release`/`VerifiedG1Release` + same-bytes copied root（`root.name==release_id`）+ 已建 tree → `verify_backtest_build_output` 必须 `M3_A_SHARE_BACKTEST_ARTIFACT_INVALID`；  
   - nested 非 `G1Release`（SimpleNamespace/duck）在任何 P0 输出前由 G7F 入口拒绝（不得依赖 F0 mock 缺席）。  
6. **通过条件**：上述两反例双平台稳定拒绝；既有 A1–A5/A4a/formal 正向/邻接/R2 fixed-order/Ruff/mypy/cold 不回归；再交未参与该返工实现的独立初验。

## 残留

- final+receipt（A4a）与 helper 路径发散（A4b）仍能拒「发布后 remap」；缺口在 **pre-final / 无 receipt** 与 **G7F nested exact**。  
- WSL 本补充未重跑（Win 已证 FAIL）；DrvFS 非 ext4 Gate。  
- G8 同步继续暂停至本 FAIL 关闭。
