# M3 G7A R3：正式 G1 Quality 来源闭包主 Agent 最终验收报告

日期：2026-08-10  
结论：**工程主验 PASS；仅解锁 G7B 同类来源闭包返工，不代表真实全折、Linux/ext4、G7 或 M3 Gate 通过。**

## 验收结论

formal G7A 已不再要求不存在的 G1 `receipt.json`。正式 14-input 闭包固定为 G1 manifest、G1 quality、
G1 eligible，随后 feature、prediction、folds、experiment；quality path 必须精确为 release root 下
`quality.json`，bytes sha256 必须等于 `VerifiedG1Release.quality_sha256`。development 专用 receipt 路径保持不变。

## 证据

- 外部实现自测：Windows formal 7 passed、development 邻接 5 passed；WSL base 合计 11 passed；两平台
  Ruff、mypy、cold import 通过。
- 全新外部独立初验：Windows/WSL 各 11 passed；另在两平台完成 quality/eligible hardlink alias、根外
  quality alias、旧伪 receipt 整包合法重签、G1 whole-root 替换、hostile 路径异常脱敏、quality 单字节漂移
  六组对抗，全部 fail closed。独立报告结论 PASS，仅解锁主验。
- 主 Agent 复核：`_formal_g1_quality_path`、`_formal_fresh_upstream_bytes`、`_formal_receipt_inputs` 与入口调用
  顺序符合任务 §10；development `_fresh_upstream_bytes`/`_receipt_inputs` 仍使用其真实 receipt。
- 主 Agent Windows 关键节点：R3 quality drift/alias/pseudo-receipt 节点 1 passed；定向 Ruff、mypy PASS。
- scoped diff-check PASS；未修改 `m3_release.py`、G1 final tree、公共 API、development 测试或正式 artifact。

## 残留边界

- WSL 证据来自 `/mnt/f` DrvFS，不是 ext4 Gate。
- 未运行真实全折 G1→G7A；真实发布链仍须后续 Gate 验证。
- G7B、G7F、G8 仍各自存在同源伪 G1 receipt 合同，必须串行返工并重新独立初验，不能沿用本报告代替。
