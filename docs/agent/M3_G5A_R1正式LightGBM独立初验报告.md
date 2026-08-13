# M3 G5A R1 正式 LightGBM 独立初验报告

日期：2026-08-08  
角色：未参与 G5A 实现的全新独立初验 Agent  
结论：**FAIL，退回实现 Agent 返工；不进入正式完整 work 训练，不宣布 G5/M3 Gate 通过**

## 1. 初验边界与结论摘要

本轮完整读取根 `AGENTS.md`、`.ai/README.md` 及其直接要求的通用规则、G5A 任务单与交付报告，并核对 G4B/G4C 的任务、交付和独立初验边界。生产代码与实现者测试全程只读；唯一新增文件为本报告。未访问网络，未触碰正式 G1/G2 artifact、journal 或候选目录，也未执行 Git 提交。

当前实现的 formal/development exact type 分界、G4C fresh verifier 调用、train/validation-only LightGBM 训练、确定性参数闭包、三文件 bundle、manifest/receipt 物理摘要、验证曲线、best iteration、延迟加载及异常脱敏总体成立。Windows 与 WSL base/DrvFS 的实现者测试、Ruff、mypy 和真实 LightGBM 冷启动也均通过。

但独立对抗探针证明 `predict_fitted_model` 会接受重复且非单调的推理行键，并接受与 DataFrame index 完全不一致的 metadata 键，然后返回可被错误证券/日期关联的分数。这违反任务单对 predict key/order 的明确核对要求，破坏“score 与 test row key 一一绑定”的系统不变量，故本轮必须判定 FAIL。

此外，任务单第 2 条要求 formal builder/verify 首先 fresh-verify alignment，而当前 builder 的公开签名没有 receipt/upstream 参数，实现也没有调用 formal alignment verifier。这是冻结文字与冻结 API 之间的真实合同矛盾；应由主 Agent 先裁定权威合同，再交实现 Agent 返工，不能由实现者自行猜测。

## 2. 合同逐项映射

| 冻结要求 | 独立证据 | 结果 |
|---|---|---|
| formal/development capability 不混用 | 三个 formal 公共入口均使用 exact `type(...) is ...`；现有交叉类型测试通过 | PASS |
| verifier fresh 重验 G4C 与完整上游 | `verify_model_artifact` 调用 formal `verify_alignment_artifact`，随后要求 fresh capability 与输入完全相等；不同绝对路径但同 bytes 的 forged return 被现有测试拒绝 | PASS |
| builder 首先 fresh-verify formal alignment | `build_model_artifact -> _build_model_artifact` 只执行 capability identity、空目录和 `load_supervised_segment`；后者重验 alignment 自身 manifest/segment bytes，但不重验 receipt、feature/label 或 G1→G4C 全链 | **合同/API 矛盾，未满足** |
| fit 只含 train/validation，禁止 test/RankIC | builder 只调用 supervised loader 的 `train`、`validation`；`lgb.train` 的 `valid_sets` 精确只有 validation，metric 为 l2，公开 fit 签名无 test | PASS |
| 参数与训练矩阵闭包 | exact 参数集合、CPU/deterministic/force_col_wise、四 seed、num_threads 和 control 分离均有代码与测试；X NaN 合法、X Inf/y non-finite、列/dtype/index/segment 重叠均 fail closed | PASS |
| 三文件、manifest、curve、receipt 闭包 | verifier 要求精确三文件，重算 model/curve hash、连续 finite curve、best iteration/l2、runtime version，并通过公共 receipt verifier核对 exact input/output 路径与 bytes；未知 receipt 字段拒绝 | PASS |
| prediction 的 schema/name/order/hash、row key 和 finite | 列名/列序、Float64 schema hash、X Inf、输出长度和 finite 已核对；**行键唯一性、单调顺序、index 名称及 metadata 与 index 一致性均未核对** | **FAIL** |
| LightGBM 延迟加载 | 只有 `model.py::_lightgbm()` 执行 `__import__("lightgbm")`；包根 import 测试与静态导入图通过 | PASS |
| Windows/WSL 与 Gate 表述 | 两平台定向验证均通过；WSL 运行于 `/mnt/f` DrvFS，非 ext4；未运行正式全 work 或性能 Gate | PASS（仅工程证据） |

## 3. 阻塞问题一：prediction 丢失 row-key/metadata 绑定

优先级：P1

- **现象**：`_predict_fitted_model` 只比较 feature columns/dtypes/schema hash，随后把裸矩阵交给 LightGBM；它不检查 index 是否为唯一、有序、名称为 `as_of/symbol` 的两级 MultiIndex，也不检查 `inference.metadata` 的 `(as_of, symbol)` 是否逐行等于 feature index。
- **根因**：实现把“特征列 schema”误当成“完整推理输入身份”。预测返回值只是位置元组，后续消费者会按 metadata 位置挂接 score；二者失配会把模型分数归属到错误日期或证券。
- **应遵循规则**：G5A 任务单明确要求预测核对 inference feature schema/name/order/hash，并把 predict key/order 漂移列为必测反例；G4C 的正常 builder 虽生成合法键，但 `InferenceSegment` 是可公开构造的普通 dataclass，G5A 公共边界仍须 fail closed。
- **最小复现**：独立内存探针构造一个 exact `VerifiedModelArtifact`，其 `InferenceSegment.features` 使用重复且乱序的 `("as_of", "symbol")` MultiIndex，metadata 则使用三组完全不同的键。当前入口成功返回：

  ```text
  G5A_ROW_KEY_METADATA_DRIFT_ACCEPTED (0.0, 0.0, 0.0)
  ```

- **新增测试**：至少分别覆盖重复 index、非单调 index、错误/缺失 index name、metadata key 与 index 值不一致、metadata 行顺序漂移；同时保留合法有序键、合法 X NaN 和 score 顺序不被排序或 rank 改写的正例。
- **通过条件**：上述五类漂移在调用 LightGBM 前以稳定脱敏 `ValueError` 拒绝；合法输入输出长度与逐行键序保持不变，并增加回归测试证明 booster 未被调用。

## 4. 阻塞问题二：formal builder fresh-verification 合同与 API 不一致

优先级：P1，先由主 Agent 冻结合同

- **现象**：任务单第 2 条写明 builder/verify 首先 fresh-verify formal alignment；当前只有 verifier 能做到。builder 的权威签名只有 alignment/feature/label/experiment/config/spec/output_root，没有 alignment receipt、上游 specs、paths 或 artifact roots，因此无法执行完整 fresh verification。
- **根因**：任务单同时冻结了“builder fresh-verify”行为和一个不足以提供 fresh verifier 依赖的 API，但实现/交付没有把该矛盾报告给主 Agent，而是把 exact frozen dataclass 当成足够强的信任边界。
- **最小复现**：正式实现测试自身从 development alignment 文件构造 `VerifiedAlignmentArtifact`，不经过公开 formal alignment verifier即能成功调用 `build_model_artifact`；这适合作为隔离 G5A 单元测试的 double，但也证明生产 builder 不会自行 fresh verify。
- **应遵循规则**：主 Agent 应先明确二选一的 SSOT：扩展 builder 所需的完整 fresh-verification 依赖；或明确 builder 只在同一受控编排事务中消费刚签发 capability，并把 fresh verification 设为调用方/编排器的可验证前置。不得同时保留互相矛盾的要求。
- **新增测试与通过条件**：按主 Agent 冻结后的方案，增加伪 exact dataclass、stale receipt、同 bytes 异路径、feature/label/upstream 漂移的 builder 反例；在任何模型文件写入或 LightGBM import 前拒绝。

## 5. 其他对抗性核验

- formal/dev capability 在 build 与 verify 边界互换：拒绝，且 builder 零写入。
- fresh alignment verifier 返回另一绝对目录、bytes 相同的 capability：以 stale 拒绝。
- `model.txt`、metadata、curve 任一 bytes 漂移：verifier 拒绝。
- receipt stage 使用 development、receipt 顶层加入未知字段：拒绝。
- prediction Float32、列 schema 漂移、X infinity、非 finite score：拒绝。
- 真实 LightGBM 4.6.0 完成 train → save → load → best-iteration predict，四个 score 均 finite。

实现者现有测试没有覆盖第 3 节的行键/metadata 反例，因此 18 个测试绿色不能消除该缺陷。

## 6. Windows 原生验证

解释器：`D:\Miniforge3\python.exe`；工作目录为本 formal worktree；`PYTHONPATH=src`；pytest 使用唯一 basetemp。

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_model_artifact.py tests/unit/test_m3_formal_model_artifact.py -q -p no:cacheprovider --basetemp=artifacts/test-tmp/g5a-independent-review-20260808
# 18 passed, 17191 warnings in 268.23s

D:\Miniforge3\python.exe -m ruff check src/quant/research/m3/model.py src/quant/research/m3/__init__.py tests/unit/test_m3_formal_model_artifact.py
# All checks passed!

D:\Miniforge3\python.exe -m mypy src/quant/research/m3/model.py src/quant/research/m3/__init__.py tests/unit/test_m3_formal_model_artifact.py
# Success: no issues found in 3 source files

D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_formal_model_artifact.py -k native_lightgbm -q -s -p no:cacheprovider --basetemp=artifacts/test-tmp/g5a-independent-native-20260808
# G5A_NATIVE_LIGHTGBM_PASS 4.6.0 3 4
# 1 passed, 3 deselected in 5.79s
```

warnings 均为现有 Pandera/Polars horizontal concat 弃用警告，不含失败。

## 7. WSL base / DrvFS 验证

解释器：`/home/mabw/miniforge3/bin/conda run -n base python`，Python 3.13.13；工作目录：`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`。

```text
pytest 同组：18 passed, 17191 warnings in 191.04s
Ruff：All checks passed!
mypy：Success: no issues found in 3 source files
native smoke：G5A_NATIVE_LIGHTGBM_PASS 4.6.0 3 4；1 passed, 3 deselected in 5.38s
```

这证明 WSL base 在 `/mnt/f` DrvFS 上的 G5A 工程合同与 native LightGBM 可运行；它不证明 ext4 文件系统语义，不替代 Linux/ext4 发布 Gate，也不关闭正式 G5/M3 Gate。

## 8. 最终结论与返工入口

G5A 当前为 **FAIL**。实现 Agent 应先修复 prediction 的 row-key/metadata fail-closed，并由主 Agent 先裁定 builder fresh-verification 的权威 API/前置语义，再完成对应实现与新增测试。返工后必须由未参与返工实现的独立初验者复验；在复验 PASS 前，不运行正式完整 folds/horizons work，不进入 G5B，不更新路线图为完成。
