# M3-G4C-R1 正式 Alignment 独立初验报告

日期：2026-08-02  
角色：全新独立初验者（未参与 G4C 实现）  
结论：**PASS（Windows 开发合同通过；WSL base 与正式 G4/M3 Gate 未关闭）**

## 1. 初验边界

本轮只读检查 `M3_G4C_R1正式Alignment任务单.md`、交付报告、G4B 正式 FeatureArtifact 合同与当前 diff。生产代码和实现测试保持只读；本报告是唯一新增文件。未修改、重启或读取正式 G1 artifact、journal、候选目录，也未提交 Git。

## 2. 合同逐项映射

| 冻结合同 | 独立证据 | 结果 |
|---|---|---|
| formal exact capability | 四个正式公开入口均以 `type(...) is ExactFormalType` 拒绝 development capability；builder 在 `_require_empty_directory` 前完成身份检查 | PASS |
| receipt 固定 `stage=alignment`、`scope=WORK`、`scope_key=work_key` | verifier 先用公共 `verify_stage_receipt_with_bytes` 重验 receipt 与输入/输出字节，再精确比较 7 个 direct inputs、4 个 outputs、stage/scope/scope_key | PASS |
| fresh feature + label 全上游闭包 | formal verifier 明确调用 G4B `verify_feature_artifact` 与正式 `verify_label_artifact`，并逐字段/Frame 与调用方 capability 比较；G4B 全链已由其独立初验覆盖，本轮 formal 调用图测试确认两个 fresh verifier 各调用一次 | PASS |
| train/validation PIT 对齐 | builder/verifier 均按 planned fold dates 取 feature/同 horizon label，执行 1:1 join；缺 label 与 `available_as_of > fold cutoff` 仅进入 diagnostics；最终标签 finite 且两个 segment 非空 | PASS |
| test inference 完全 label-free | 正式公开签名无 label/label receipt/horizon/cutoff；调用图只 fresh verify feature/fold 并读取 test feature parquet，不读取 label artifact | PASS |
| manifest/物理内容闭包 | manifest 严格字段、重复 key 与 canonical bytes 校验；tree 固定四文件；segment bytes、row keys、matrix、labels、计数、diagnostics 均从物理内容重建 | PASS |
| supervised loader | 仅接受 exact `VerifiedAlignmentArtifact` 与 train/validation；重验 canonical manifest 相等及目标 segment 的物理 bytes/row/matrix/label digest | PASS |
| 包根与重依赖隔离 | 包根同时导出 formal/development API；定向测试确认 import graph 未引入 qlib/lightgbm/mlflow | PASS |

## 3. 独立对抗性反例

除实现者报告外，本轮额外运行一个不落盘源码的临时探针，共享最小 fixture，但单独构造 formal alignment 与 receipt：

1. 让 feature fresh verifier 返回语义指向同目录、但包含 `..` 的非规范绝对路径 capability：verifier 以 `alignment upstream stale` 类失败拒绝。
2. 让 label fresh verifier 返回 receipt digest 被伪造的 formal capability：拒绝。
3. 将完整 formal artifact 与 development-alignment receipt 混配：即使直接输入路径同形，仍因 stage/receipt 闭包不符而拒绝。
4. 将正式 label verifier 以及 `labels.parquet`/`diagnostics.parquet` reader 全部改为抛错：formal inference 成功，输出 metadata 与 feature test segment 的全部 scorable keys 完全一致。

探针输出：

```text
G4C_INDEPENDENT_ADVERSARIAL_PASS path_drift forged_return mixed_receipt label_free_keys
```

实现测试同时覆盖 whole manifest/receipt bytes 漂移、未知/额外 direct input、formal/development capability 互换、跨 work/horizon/planned-fold/feature/label identity、duplicate key、late/missing/non-finite label、空 segment、row order/matrix/signed-zero 等 fail-closed 反例；本轮完整执行而非只选择绿色子集。

## 4. Windows 定向验证

解释器：`D:\Miniforge3\python.exe`；工作目录为本 worktree；pytest 使用唯一 basetemp。

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_alignment.py -q -p no:cacheprovider --basetemp=artifacts/test-tmp/g4c-review-20260802
# 17 passed, 21793 warnings in 271.85s

D:\Miniforge3\python.exe -m ruff check src/quant/research/m3/alignment.py src/quant/research/m3/__init__.py tests/unit/test_m3_alignment.py
# All checks passed!

$env:MYPYPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/alignment.py src/quant/research/m3/__init__.py
# Success: no issues found in 2 source files
```

pytest 的 21793 条 warning 均为现有 Pandera/Polars horizontal concat 弃用警告，不含失败。

## 5. WSL 与剩余 Gate

当前会话已知 WSL 启动受宿主权限/额度状态阻塞；依任务要求，本轮未重复触发同一失败。故本报告只确认 Windows 开发合同通过，不宣称 WSL base 通过，也不关闭正式 G4/M3 Gate。

后续仍需在 WSL base 执行同组定向验证，并完成正式 LightGBM、evaluation、冷启动复现，以及在最终冻结 source identity 下重发 G1/G2 正式链。Windows 结果不替代 Linux/WSL Gate。

## 6. 最终结论

G4C-R1 的正式 Alignment、监督加载与 label-free inference 满足冻结合同，新增独立反例未发现绕过，**独立初验 PASS**。可进入主 Agent 最终验收；Gate 状态必须继续表述为“Windows 开发合同通过，正式 G4/M3 Gate 待 WSL 与真实后续链关闭”。
