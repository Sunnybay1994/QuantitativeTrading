# M3 G1：`audit_g1_candidate` FULL_DAY×required 集合预构建性能修订

- 日期：2026-07-24
- 环境：Windows 原生（`D:\Miniforge3\python.exe`）
- **不宣称** Gate / Codex 终验

## 现象

正式 `run_g1 status` 在 `build_g1_candidate` + `verify_g1_candidate` 通过后，卡在 `audit_g1_candidate` 数小时；`py-spy` 栈定点：

`m3_g1_candidate.py` 对每个 `full_day` key 现场重建 `required.iter_rows` 集合。

## 根因

```text
for key in full_day:
    if (...) in { (... ) for row in required.iter_rows(...) }:
```

复杂度约 `O(|FULL_DAY| · |required|)`，全量 G1 不可接受。

## 修订

先构建一次 `required_trade_symbol_keys`，再对 `full_day` 做成员判定；语义不变。

## 验证

- `pytest tests/unit/test_m3_g1_candidate.py -k "audit or full_day or price_limit"` → 4 passed
- 继续 Windows 正式 `run_g1 status` / 必要时 `history`
