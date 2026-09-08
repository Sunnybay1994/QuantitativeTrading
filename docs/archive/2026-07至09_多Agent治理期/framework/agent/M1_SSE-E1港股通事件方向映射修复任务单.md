# M1 SSE-E1 港股通事件方向映射修复任务单

## 1. 现象与根因

2026-07-17 主 Agent 使用项目官方 `SseConnectConnector` 做不落盘审计，SSE 事件端点返回的
`ADJUST_TYPE` 唯一值为“调进”（794 行）和“调出”（418 行）。当前 `map_sse_events` 却以
`ADJUST_TYPE == "01"` 判定 ADD，其余一律 REMOVE，导致 1,212 条当前官方事件全部映射为 REMOVE。
现有单测使用了脱离真实 SDK 的伪值 `"01"`，因此未发现问题。

该问题破坏港股通 Point-in-Time 资格状态机，优先级 P0。本包只修零网络代码与测试；不得修改或重建现有
raw/clean/universe 数据。

## 2. 冻结合同

1. `map_sse_events` 只接受官方观测值：去除首尾空白后的“调进”→`ADD`，“调出”→`REMOVE`。
2. null、空串、`"01"`、`"02"`、英文 ADD/REMOVE、未知中文均须在返回 DataFrame 前以稳定、脱敏
   `ValueError("SSE_EVENT_ADJUST_TYPE_INVALID")` 拒绝；不得把未知值默认映射为 REMOVE。
3. 输入必须包含 mapper 所需精确列；既有 Polars 缺列异常可保留，不扩大公共异常重构。
4. 其他字段、Schema、route/source/security_type/published_date 语义不变。
5. 更新测试为真实中文 raw 值，覆盖 ADD、REMOVE、首尾空白、混合合法值，以及每种非法值。
6. 添加最小状态机回归：一只当前成员，经“调进后调出再调进”等合法序列映射后 action 顺序正确；不得修改
   `eligibility.py` 或用测试绕过 mapper。
7. 禁止网络、data 读写、迁移、全量 pytest、Git 初始化。

## 3. 文件白名单

- `src/quant/data/connect_market.py`
- `tests/unit/test_connect_market.py`
- `docs/framework/agent/M1_SSE-E1港股通事件方向映射修复交付报告.md`

## 4. 定向验证

WSL Miniforge base：

```bash
python -m pytest tests/unit/test_connect_market.py -q
python -m pytest tests/unit/test_eligibility.py -q
ruff check src/quant/data/connect_market.py tests/unit/test_connect_market.py
mypy src/quant/data/connect_market.py
```

实现与独立初验使用不同全新 `cursor-grok-4.5-high` 会话。初验生产代码/实现测试只读，唯一允许写
`docs/framework/agent/M1_SSE-E1港股通事件方向映射修复独立初验报告.md`；初验须增加“合法与未知值同批出现时整批
失败、不得返回部分映射”的 `/tmp` 反例。

通过不代表现有 clean 事件已修复；后续必须单独设计并授权 raw 保留、clean 原子重建和历史区间再发布。
