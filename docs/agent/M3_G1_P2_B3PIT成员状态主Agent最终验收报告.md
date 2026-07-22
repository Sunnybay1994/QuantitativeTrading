# M3 G1-P2 B3 PIT 成员状态主 Agent 最终验收报告

> 后续修订：2026-07-17 真实 INDEX 运行证明，月频 observation 与月中退市会合法地产生短暂 299 eligible。
> 本报告关于“eligible_keys 始终精确 300”的旧验收结论已由
> [`M3_G1_R1C-B_INDEX身份合同返工任务单.md`](M3_G1_R1C-B_INDEX身份合同返工任务单.md) 取代；
> observation 精确 300 的门禁仍保留。

日期：2026-07-14  
结论：**G1-P2/B3 通过主 Agent 最终验收**  
边界：只关闭 PIT 成员观察、成员区间、资格键和 clean identity 子包；不关闭 B2、G1、M3 或任何 Gate

## 1. 完整证据链

| 阶段 | 证据 |
|---|---|
| 配置前置 | [`M3_G1_P2_0主Agent最终验收报告.md`](M3_G1_P2_0主Agent最终验收报告.md) |
| 冻结任务 | [`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](M3_G1_P2_B3PIT成员状态外部闭环任务单.md) |
| 首次外部实现 | [`M3_G1_P2_B3PIT成员状态交付报告.md`](M3_G1_P2_B3PIT成员状态交付报告.md) |
| 首次独立初验（不通过） | [`M3_G1_P2_B3PIT成员状态独立初验报告.md`](M3_G1_P2_B3PIT成员状态独立初验报告.md) |
| P1-1 返工任务 | [`M3_G1_P2_B3PIT成员状态初验一次返工任务单.md`](M3_G1_P2_B3PIT成员状态初验一次返工任务单.md) |
| 原实现者返工 | [`M3_G1_P2_B3PIT成员状态初验一次返工交付报告.md`](M3_G1_P2_B3PIT成员状态初验一次返工交付报告.md) |
| 全新 Agent 独立复验 | [`M3_G1_P2_B3PIT成员状态初验一次返工独立复验报告.md`](M3_G1_P2_B3PIT成员状态初验一次返工独立复验报告.md) |

实现、首次初验和返工复验使用不同 Cursor 会话；全部显式使用 `cursor-grok-4.5-high`，没有使用 Fast 变体。
Windows Cursor Agent 的项目工具均通过 `wsl.exe` 在 WSL Miniforge `base` 运行。首次初验发现问题后回到
原实现者返工，再由未参与实现的新会话复验，职责分离成立。

## 2. 最终业务与身份结论

- normalize 在读取 raw 行值前重建 `TushareRequestBatch` 与每个 `VerifiedRawResponse`，证明完整连续自然月、
  request ID 多重集合、spec/receipt/hash/frame 闭包和固定 `index_weight/000300.SH` 范围。
- 每个 observation 保留供应商日期且恰好 300 只，权重用确定性顺序与 `math.fsum` 验证 `[99,101]`；重复键、
  空月、跳月、跨 scope 和非法 dtype 均 fail-closed。
- observation 后下一 SH session 收盘才形成 `as_of`，最早再下一 session open 成交；signal window、warmup、
  SH/SZ 自然日一致性、尾部严格下一 session proof 和 instrument 生命周期均显式验真。
- membership 按 signal window 和生命周期裁剪、连续区间合并、调出/重入保留；每个 signal session 的
  `eligible_keys` 仍必须精确 300。
- `m3-clean-table-content-v1` 绑定 table name、列顺序/dtype、规范 scalar 和重复次数，行序无关，datetime 与
  非 finite 值拒绝。
- `ObservedMembershipResult` 成功构造时，三张 validator 返回 frame 均写回公开属性，再基于公开 frame 验
  digest；严格 verifier 仍从 raw/batch/calendar/instrument 重建，拒绝整体自洽但来源不符的结果。

## 3. 外部初验发现与可复用教训

首次实现虽有 560 项全量绿测，`__post_init__` 仍使用 coerced frame 算摘要却暴露预验证 frame，形成
“公开表与摘要描述不同内容”的 P1-1。根因不是 verifier 缺失，而是值对象构造边界没有消费 Schema 返回值。

返工规则已写回任务书和 M3 SSOT：带 coercion 的 validator 不是旁路检查；成功对象必须保存 validator 返回
对象，并只基于实际公开值计算 identity。该规则适用于后续 P3/P4 的所有 frozen result/dataclass。

## 4. 主 Agent 未公开反例

主验未复用外部 Agent 的 2016/2024 精确列组合：

| 反例 | 结果 |
|---|---|
| 三表日期转 Utf8，字符串列转 Categorical，但数值保持等值 | 三表写回规范 dtype；公开摘要逐表闭合；完整 raw 来源 verifier 通过 |
| observations 权重额外降为 Float32，产生有损数值变化 | 构造对象内部摘要仍自洽，但完整 raw 来源 verifier 稳定拒绝 `G1_MEMBERSHIP_RESULT_INVALID`，无 cause 泄露 |

隐藏脚本最终输出：

```text
P2-B3 MAIN HIDDEN EQUIVALENT COERCION: PASS
P2-B3 MAIN HIDDEN LOSSY ORIGIN CLOSURE: PASS
```

## 5. 主 Agent 验证结果

全部使用 WSL Miniforge `base`：

| 验证 | 结果 |
|---|---|
| membership/identity/backfill/mappers 定向 | **168 passed** |
| 全量 `pytest -q` | **562 passed**，2867 条既有/已知 deprecation warnings |
| Ruff | All checks passed |
| mypy | 75 source files，0 issues |
| 主 Agent 隐藏反例 | 两支全部通过 |

## 6. 已知非阻断项

Polars 已提示直接 `String→Date` cast 将在 2.0 移除；当前版本行为确定，且 Pandera coercion 路径也产生同类
既有告警。记录为依赖升级债务，不影响当前 PIT、identity 或来源闭包；升级 Polars/Pandera 时统一迁移并保留
这些回归测试，不在本包顺手改写。

## 7. 状态边界与下一步

本报告只关闭 G1-P2/B3。B2 仍缺 P3/B2C 执行事实，G1 仍缺 P3、P4、真实全量数据、跨源对账与不可变
release，所以不更新 `项目实施路线图.md` 或 G0–G9 Gate。

下一包可按 [`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)
进入外部实现—独立初验闭环。
