# M3 G7A R2：Decimal 循环小数算术返工交付报告

日期：2026-08-09  
状态：最小返工与双平台定向自测完成；待全新独立复验和主 Agent 最终验收

## 1. 返工问题与根因

R1 在 `cash_buffer=0.1`、`max_weight=0.2`、`n_selected=7` 的合法未封顶分配中，用默认 Decimal context
先计算有限精度 `0.9/7`，再乘回 7 得到向上尾差，误触发超配断言。formal 与 development 原先各复制了
同一缺陷。

## 2. 最小修复

- 新增单一私有 `_target_allocation`，formal `_build_frames_from_layers` 与 development `_build_target_frames`
  均只调用该 helper，不再各自实现权重算术。
- helper 用 `Fraction(Decimal)` 的精确有理数比较判定
  `max_weight * n_selected <= 1-cash_buffer` 的 capped 分支。
- 未 capped 分支只在模块私有 `Context(prec=50, rounding=ROUND_DOWN)` 的副本中计算 weight；total 也由同一
  context 重算，保留 `total <= investable` 的 fail-closed 断言。
- Decimal 构造、减法、除法和乘法不读取调用方全局 Decimal context；未引入 epsilon/tolerance，也未改变
  manifest、receipt、公开签名、三文件格式或 G7B 接口。

## 3. 新增回归

- formal：构造两个 test dates、每日至少 8 个 eligible、7 个 scorable/predicted，selector 固定
  `top_k=7/cash_buffer=.1/max_weight=.2`；在 hostile 全局
  `Context(prec=2, rounding=ROUND_UP)` 内完成 build→receipt→verify。
- formal 断言：16 个完整 eligible target 行、14 个正权重、2 个显式零、manifest `n_selected=14`，两日 total
  精确等于私有 helper 结果且不超过 `0.9`。
- development：直接执行 development `_build_target_frames`，以 monkeypatch 计数证明逐日调用同一
  `_target_allocation`；同测固定 `0.9/7` 正例。

## 4. 验证结果

Windows 原生 Miniforge：

- R2 新增两节点：`2 passed`，53.70 秒。
- formal 全套与直接 development 数学回归：`12 passed`，166.47 秒。
- Ruff：实现及两份相关测试 `All checks passed`。
- mypy：`targets.py` `Success: no issues found`。

WSL Miniforge `base`：

- 同一 12 节点：`12 passed`，85.74 秒。
- Ruff、mypy 均通过。
- 文件系统为 `wslfs`；该结果是 WSL/DrvFS 兼容性证据，不是 ext4/Linux Gate。

## 5. 边界

本轮只关闭独立初验报告中的 Decimal 唯一阻断。未修改公开接口、G1--G6、development receipt/schema、
正式 artifacts/journal 或 G7B；未 add/commit。G7A 仍需未参与返工的全新 Agent 独立复验 PASS，再进入主验。
