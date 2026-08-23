# M3 G5A development example LightGBM 模型阶段验收

日期：2026-08-02
信任域：`development_example`（`formal_gate_eligible=false`）

## 结论

G5A 的 development example 工程合同已实现并通过双平台定向验证。该结论只证明隔离示例链可以构造、
验真并消费 native LightGBM 模型产物；不代表 production G5、真实数据科学结论或 Linux/ext4 Gate 关闭。

## 冻结边界

- 仅 `model.py` 延迟 import `lightgbm`；包根、domain、strategies、backtest 和 execution 均不加载它；
- builder 只接收 G4C fresh-verified train/validation 对齐，不接受 test；X 允许 NaN、拒绝 infinity，y 必须
  finite，两个 segment 的列序、Float64、唯一有序 MultiIndex 和 X/y 行键必须严格一致且互不重叠；
- booster 参数与训练 controls 分离；参数闭包固定 regression/l2、CPU、deterministic、force_col_wise、
  四 seed 和线程数，只用 validation l2 early stopping；
- 输出闭包精确为 `model.txt`、`model.metadata.json`、`validation_curve.parquet`，manifest 绑定完整上游
  identity、矩阵/标签/row-key 摘要、参数、运行时版本、best iteration/score 和文件哈希；
- verifier fresh-verify 全上游、精确 receipt 输入/输出闭包和三个输出 bytes，development verified type 保留
  `development_example` 身份，不能构造或冒充 `VerifiedModelArtifact`；
- inference 只按保存的 best iteration 评分，核对列序且拒绝非 finite score，不做 rank、不接 label。

## 实现与对抗测试

- 新增 LightGBM training spec、model manifest/upstream path、formal/development verified 值对象；
- 新增 development builder、strict reader、fresh verifier、best-iteration predictor 和参数身份哈希；
- 14 项测试覆盖参数/control 闭包、delayed import、validation-only l2、NaN/Inf、dtype/列序/MultiIndex、
  train-validation 泄漏、curve-best 对账、三个文件篡改、receipt、跨身份/no-clobber 和 prediction；
- 真实 LightGBM 4.6.0 冷启动发现原生 `best_score` 为 `defaultdict/OrderedDict`。实现已从精确 `dict`
  修正为接受 `Mapping`，同时仍严格核对 `validation/l2` 数值，并新增原生结构回归测试。

## 验证证据

Windows 原生 Miniforge：

```text
PYTHONPATH=<worktree>/src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_model_artifact.py -q
14 passed in 186.17s

D:\Miniforge3\python.exe -m ruff check src/quant/research/m3 tests/unit/test_m3_model_artifact.py
All checks passed!

D:\Miniforge3\python.exe -m mypy src/quant/research/m3
Success: no issues found in 22 source files
```

WSL Miniforge `base` 对同一 worktree：

```text
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output env \
  PYTHONPATH=/mnt/f/.../m3-g8ab-prereq/src python -m pytest \
  /mnt/f/.../tests/unit/test_m3_model_artifact.py -q
14 passed in 93.01s
```

该结果证明 Linux 运行时的 development 合同兼容性，不替代正式发布的 ext4 Gate。两平台均产生
Pandera/Polars `horizontal` 默认行为弃用告警，不影响本轮断言。

Windows 原生 LightGBM 4.6.0 冷启动使用同一最小上游 fixture，并把 early-stop 窗口缩为 3 以适配 4 行
训练集，只用于 SDK 接口兼容验证：

```text
G5A_REAL_OBSERVED 1 defaultdict(... {'validation': OrderedDict({'l2': np.float64(0.0)})})
G5A_REAL_LIGHTGBM_PASS 4.6.0 1 5
```

该 smoke 证明 native train/save/load/predict 形态可用，不是模型有效性或正式参数窗口证据；最小 fixture
因默认 `min_data_in_leaf` 没有形成有效分裂，不能产生性能结论。

## 尚未关闭

- production G4B/G4C 对正式 G2/G3 verified artifacts 的链路；
- 正式配置、正式数据和完整 folds/horizons 上的 G5A 训练与验真；
- G5B prediction artifact、G6 evaluation、G7 回测、G8 复现/追踪和 G9 Gate；
- Linux ext4 Gate 与真实模型性能结论。
