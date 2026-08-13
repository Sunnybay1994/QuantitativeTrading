# M3-G4C-R1 正式 Alignment 交付报告

日期：2026-08-02  
状态：Windows 定向实现与验证通过；WSL base 验证受宿主 WSL 服务访问状态阻塞；不宣称 G4/M3 Gate 关闭。

## 交付范围

- 在既有 `m3-alignment-artifact-v1`、matrix digest 和 strict receipt 契约上新增正式 API：
  `build_alignment_artifact`、`verify_alignment_artifact`、`load_supervised_segment`、
  `build_inference_segment`。
- 正式 builder/verifier 只接收 exact formal verified capability；development/formal 混用在写入或读取前失败。
- 正式与 development 共用同一构建、重建、摘要和内容校验核心；仅 capability、上游 verifier、receipt stage
  和返回 capability 分流，没有复制第二套 artifact 格式。
- 正式 receipt 固定为 `stage="alignment"`、`scope="WORK"`、`scope_key=work_key`；development stage
  保持 `development-alignment`。
- 正式监督 loader 只允许 train/validation，并重验 manifest 与物理 segment 摘要。
- 正式 inference 公共签名及调用图不含 label、label receipt、horizon 或 cutoff；只 fresh verify feature/fold
  闭包并读取 test feature segment。
- 包根同步导出四个正式 API，保持 development API 并行可用。

## 关键反例

- formal builder 接收 development capability 时零写入失败；formal verifier 接收 development feature 时在
  fresh verifier/文件读取前失败。
- 正式 alignment 的测试链明确记录 feature 与 label fresh verifier 调用；监督验签各一次。
- 将 label verifier 以及 labels/diagnostics parquet 读取设为抛错后，正式 inference 仍成功；feature fresh
  verifier 再调用一次，label verifier 调用次数不增加，test scorable keys 保持不变。
- 既有共享核心测试继续覆盖 work/horizon/schema/identity 混配、重复键、late/missing label、NaN/inf、空
  segment、物理 bytes、manifest/receipt、direct closure 和 no-clobber 漂移。

测试中的 formal 上游 capability 使用 exact formal dataclass 与受控 fresh-verifier doubles，以便只隔离验证
Alignment 的正式边界和调用图；生产 verifier 不接受 development 类型，也没有 frozen dataclass 直通分支，
而是调用正式 `verify_feature_artifact` 与 `verify_label_artifact` 后再重建 Alignment。完整正式 Feature 上游公共链
由 G4B 的独立测试覆盖，本任务未修改或重复该实现。

## Windows 验证

解释器：`D:\Miniforge3\python.exe`

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_alignment.py -q -p no:cacheprovider --basetemp=artifacts/test-tmp/g4c-final
# 17 passed, 21793 warnings in 268.12s

D:\Miniforge3\python.exe -m ruff check src/quant/research/m3/alignment.py src/quant/research/m3/__init__.py tests/unit/test_m3_alignment.py
# All checks passed!

$env:MYPYPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/alignment.py src/quant/research/m3/__init__.py
# Success: no issues found in 2 source files
```

pytest warnings 均来自 Pandera/Polars `concat(how='horizontal')` 的现有弃用告警，没有新增测试失败。

## WSL base 验证

尝试命令：

```powershell
wsl.exe -e bash -lc "cd /mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal && /home/mabw/miniforge3/bin/conda run -n base python -m pytest tests/unit/test_m3_alignment.py -q -p no:cacheprovider --basetemp=/tmp/m3-g4c-alignment-pytest"
```

宿主在创建 WSL 实例前返回：

```text
Wsl/Service/CreateInstance/E_ACCESSDENIED
```

因此本报告只声明 Windows 开发/合同验证通过；WSL base 同组验证、正式 G4/M3 Gate、正式 LightGBM、
evaluation、冷启动复现及当前 source identity 下的 G1/G2 重发布仍待后续 Gate。

## 文件边界

本轮仅修改：

- `src/quant/research/m3/alignment.py`
- `src/quant/research/m3/__init__.py`
- `tests/unit/test_m3_alignment.py`
- 本报告

工作树中既有 G4B 代码、测试、任务书与报告保持原状；未修改正式 G1 artifact、候选目录、配置或 journal，
未提交 Git commit。
