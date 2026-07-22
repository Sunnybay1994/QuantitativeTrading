# M3 G1-P2-0 主 Agent 最终验收报告

日期：2026-07-14  
结论：**G1-P2-0 通过主 Agent 最终验收**  
边界：只关闭信号边界示例与 PIT 成员方法配置修正；不关闭 P2、G1、M3 或任何 Gate

## 1. 证据链与职责分离

| 阶段 | 证据 |
|---|---|
| 冻结任务 | [`M3_G1_P2_0信号边界与成员方法配置修正外部闭环任务单.md`](M3_G1_P2_0信号边界与成员方法配置修正外部闭环任务单.md) |
| 外部实现 | [`M3_G1_P2_0信号边界与成员方法配置修正交付报告.md`](M3_G1_P2_0信号边界与成员方法配置修正交付报告.md) |
| 外部独立初验 | [`M3_G1_P2_0信号边界与成员方法配置修正独立初验报告.md`](M3_G1_P2_0信号边界与成员方法配置修正独立初验报告.md) |

实现与初验角色不同；独立初验没有修改生产代码或实现者测试。两份报告均未越权宣称 P2、G1 或 Gate
完成，符合四段式交付边界。

## 2. 最终契约结论

- 示例 signal window 已修正为 `2016-01-04..2026-06-26`，两端仍由后续 G1 verified SH calendar 验真；
  loader 没有硬编码交易日，也不自动对齐闭市日。
- PIT 成员方法的唯一 literal 为 `tushare_monthly_observed_next_session_close_v1`；旧
  `tushare_monthly_observed_next_open_v1`、近似拼写和非法类型均 fail-closed。
- `g1_backfill.membership_method_version` 的 selector 精确为 `{"g1"}`；`data.start_date` 只传播到
  `full/snapshot/scientific`。示例双字段迁移因此只改变 `full/g1/snapshot/scientific`。
- 配置闭包保持 151 assignments、138 shapes；费用首段自然日 `effective_from=2016-01-01` 未被错误对齐。
- 生产 loader 未增加 alias、trusted hash 绕过或 signal-date 自动对齐函数；核心配置 import 不引入
  Qlib、LightGBM 或 MLflow。

## 3. 主 Agent 未公开反例

主验没有复用外部报告的精确日期与组合：

| 反例 | 结果 |
|---|---|
| `start_date=2016-01-05` | 仅 `full/snapshot/scientific` 改变，`g1` 与其余 identity 不变 |
| `start_date=end_date=2026-06-26` | 可加载；传播集合仍精确为 `full/snapshot/scientific` |
| 旧 method + acceptance mutation + 含路径/token-like 的无关 purpose | 稳定 `VALUE_ERROR`；message/repr/traceback 不泄露敏感值，`__cause__ is None` |
| 生产代码 alias/日期硬编码静态检查 | 旧 literal 不存在；新 literal 唯一；无 `2016-01-04` 硬编码 |

隐藏验收脚本输出 `P2-0 MAIN HIDDEN ACCEPTANCE: PASS`，只读执行且未落盘临时产物。

## 4. 主 Agent 验证

全部使用 WSL Miniforge `base`：

| 验证 | 结果 |
|---|---|
| `tests/unit/test_m3_config.py` | **80 passed** |
| 全量 `pytest -q` | **537 passed**，1989 条既有 Pandera/Polars deprecation warnings |
| Ruff | All checks passed |
| mypy | 73 source files，0 issues |
| 主 Agent 隐藏反例 | 全部通过 |

Windows/WSL localhost proxy 提示发生在命令结束后，WSL 项目命令自身均为 exit 0，不是项目缺陷。

## 5. 状态边界与下一步

本报告只关闭 P2-0 配置前置。C0 的既有验收结论不变；P2/B3 尚未实现，G1 仍缺 P2、P3、P4、真实全量
抓取、跨源对账和不可变 release，因此不更新 `项目实施路线图.md` 或任何 G0–G9 Gate。

P2-0 前置现已满足，下一包可按
[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](M3_G1_P2_B3PIT成员状态外部闭环任务单.md)
进入外部实现—独立初验闭环。
