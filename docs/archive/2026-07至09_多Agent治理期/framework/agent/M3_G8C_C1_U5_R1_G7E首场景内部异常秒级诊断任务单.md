# M3 G8C-C1 U5 R1：G7E 首场景内部异常秒级诊断任务单

日期：2026-08-12  
状态：**U5 已完成：`INSUFFICIENT_INTERNAL_EVIDENCE`（honest chain 内部 exact 未观测）；public 翻译链与 fixture 差异已冻结**  
报告：[M3_G8C_C1_U5_R1_G7E首场景内部异常秒级诊断报告.md](M3_G8C_C1_U5_R1_G7E首场景内部异常秒级诊断报告.md)  
前置：U4 cleanup/handshake PASS；唯一 Diagnostic 已终态 EXIT=1，禁止重跑

## 1. 唯一目标

不重跑 73 分钟 honest chain，只利用 U4 已冻结证据、当前生产源码及已有 G7E/G7F 单元 fixture，在系统临时目录构造秒级、无仓库持久写入的诊断，定位 `simulate_formal_a_share_scenario(... multiplier=Decimal("0.5"))` 被 public hostile boundary 脱敏前的**首个内部异常 exact type、触发函数/不变量与最小输入差异**。

本包只做诊断，不修改产品/测试，不宣布 G7E/G7F/C1/G8 Gate。

## 2. 冻结方法

- 先只读映射 public `simulate_formal_a_share_scenario` 到私有 core 的真实参数与异常翻译点。
- 优先复用 `test_m3_g7e_formal_a_share_simulator.py`、golden、G7F formal test 已有普通/public builders；禁止 `object.__new__`、伪 capability、修改 HMAC/registry/seal 或绕过 exact type。
- 允许在独立临时目录创建一次性 pytest/plugin/script，通过 wrapper/monkeypatch **只观察私有 core 抛出的原始异常**；不得改变输入、返回值、控制流或把异常吞掉后继续。
- 可运行 seconds/minutes 级定向节点；禁止运行 U4 integration node、完整 G1→G8 chain、全量 pytest 或联网。
- 必须对照一个现有可通过的 G7E/G7F fixture与 U4 honest-chain 输入身份/形状，区分产品缺陷、fixture退化、配置不一致或证据不足。
- 若现有 retained/public值不足以重现内部异常，必须精确报告缺失的最小值/字段和下一诊断方法，不得猜根因。

## 3. 报告必须回答

1. U4 首失败之前哪些边界已成功，证明哪些输入已 fresh；
2. public `AShareSimulationError` 的内部原始异常 exact type/message类别（脱敏，禁止路径/秘密）；
3. 首个触发函数、行级不变量、相关 symbol/date/shape/Decimal 类别；
4. 为什么现有 G7E/G7F 单测未覆盖，或为何 U4 fixture 与其不同；
5. 现象—根因—应遵循规则—最小复现—新增测试—通过条件；
6. 最小实现白名单。只有证据指向时才允许建议 `a_share_simulator.py` / `a_share_reporting.py` /特定测试；不得默认扩大到 stage/publication/CLI。

## 4. 写入与禁止项

仓库唯一允许写入：

- 本任务状态；
- `docs/framework/agent/M3_G8C_C1_U5_R1_G7E首场景内部异常秒级诊断报告.md`。

临时诊断文件仅可在新建的系统临时目录内，结束后保留脱敏摘要或精确清理其自有临时文件；不得删除 U4 证据。生产、测试、config、data、artifacts、support及历史报告只读。禁止联网、add/commit/push。

## 5. 通过与停止条件

诊断 PASS 的含义仅是获得可复现、可冻结的内部首失败证据；不是产品 PASS。若只能观察到同一个 hostile public error、需要重跑 honest chain、需要伪造 formal capability或修改仓库代码，立即停止并诚实报告 `INSUFFICIENT_INTERNAL_EVIDENCE`。

