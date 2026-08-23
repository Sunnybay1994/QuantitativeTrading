# M3 G5A R2：正式 LightGBM 交付报告

日期：2026-08-08  
状态：实现与自测完成；等待独立初验和主 Agent 终验

## 改动

- formal `build_model_artifact` 现在接收完整 G1→G4C fresh-verification 依赖，并在检查输出目录或触发
  LightGBM 训练前调用正式 alignment verifier；fresh capability 与传入 alignment（含绝对 root）不 exact
  相等时 fail closed。
- development-example builder 的接口和信任边界保持不变；formal verifier 与 builder 复用同一正式 fresh
  helper，避免两处依赖闭包漂移。
- fitted-model prediction 增加 row identity 闭包：exact 两级唯一递增 MultiIndex、固定 names、metadata 精确
  `as_of/symbol` 两列与 Date/String schema、行数和逐行键同序相等；不排序、不修复输入。
- 新增 copied-root 在写入/训练前拒绝，以及 index/metadata 重复、乱序、命名、列和键漂移反例。

## 验证

- Windows Ruff：`python -m ruff check src/quant/research/m3/model.py tests/unit/test_m3_formal_model_artifact.py`：PASS。
- Windows mypy：`python -m mypy src/quant/research/m3/model.py`：PASS（1 source file）。
- Windows 完整 formal 合同与 native LightGBM smoke：
  `python -m pytest tests/unit/test_m3_formal_model_artifact.py -q`：5 passed（100.04s）。
- WSL base `/mnt/f`：同一 pytest 5 passed（41.29s），Ruff PASS，mypy PASS（1 source file）。该路径为
  DrvFS，只是 Linux interpreter 双平台反馈，不代表 ext4 Gate。

## 完成边界

本交付只修复 G5A formal builder freshness 与 prediction row-key 合同。未运行正式全量 folds/horizons 训练，
未关闭 G5B–G9、真实性能、Linux/ext4 或 M3 Gate；未触碰正式 artifacts、journal 或候选目录。
