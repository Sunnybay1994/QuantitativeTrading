# M3 G1-P4A：主 Agent 最终验收报告

日期：2026-07-14  
结论：**P4A primary candidate 与全局主源审计子包通过主 Agent 最终验收**  
边界：不宣称 B4、G1、M3 或任一 Gate 完成；P4B/P4C 尚未实现

## 1. 完整验收链路

- 冻结设计：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)
- 原实现：[`M3_G1_P4A候选与主审计交付报告.md`](M3_G1_P4A候选与主审计交付报告.md)
- 原独立初验：[`M3_G1_P4A候选与主审计独立初验报告.md`](M3_G1_P4A候选与主审计独立初验报告.md)，结论通过
- 主验返工：[`M3_G1_P4A主验一次返工任务单.md`](M3_G1_P4A主验一次返工任务单.md)
- 原实现者返工：[`M3_G1_P4A主验一次返工交付报告.md`](M3_G1_P4A主验一次返工交付报告.md)
- 全新外部复验：[`M3_G1_P4A主验一次返工独立复验报告.md`](M3_G1_P4A主验一次返工独立复验报告.md)，结论通过

实现与复验使用不同 Cursor 会话，模型均为 `cursor-grok-4.5-high`；所有项目命令在 WSL Miniforge `base`
运行。主 Agent 未在返工阶段代替实现者修改生产代码。

## 2. 主验发现及关闭

原初验覆盖了 audit/verify 对 wholesale candidate 和 digest 漂移的拒绝，却漏测公共构造器本身。
`G1Candidate.__post_init__` 当时只检查 64 hex 与 digest 表形状，因此 `replace(candidate,
primary_candidate_key="f"*64)` 或改 frame 保留旧 digest 仍可构造。这违反“公共值对象身份自证”，定为 P1-1。

返工后 constructor 从对象内证据完成三层重算：

1. 14 张表经 Schema/coercion 规范化并写回，再逐表重算 content digest；
2. 从 calendar/instrument/eligible/suspension/history 重建 required price-limit keys digest；
3. 从 build spec、plan、四日期、receipt、重算表 digest 与 required digest 重算唯一 primary key。

任一 frame/digest/required/key 漂移构造即失败；audit 仍负责多问题收集，带原始 inputs 的 verify 仍负责重执行
来源闭包，三层职责未合并或削弱。

可复用教训已写回冻结设计：验证 `audit/verify` 通过不能代替直接攻击公共 dataclass constructor；“合法 64 hex”
也不等于派生身份自证。

## 3. 主 Agent 二次隐藏反例

主 Agent 用临时测试文件执行后删除，未将验收 harness 留入仓库：

1. 把 P3 reconciliation 的 `event_ids_json` 从 Utf8 改为 Categorical，但业务值不变：constructor 必须先
   Schema 写回 Utf8，再核对原 digest；构造后 digest 不漂移，原 inputs verify 通过。
2. 把 `event_ids_json` 改为业务非法但 Schema 可表达的非规范 `[ ]`，同时重绑整套 P4A table digest/primary：
   constructor 接受内部身份自洽对象；audit 产生 `CORPORATE_ACTION_FACTOR_MISMATCH`，带原 inputs 的 verify 以
   `G1_CANDIDATE_IDENTITY_MISMATCH` 拒绝且 `__cause__ is None`。这证明 constructor identity、audit 业务门禁和
   verify 来源闭包各守边界。

结果：**2 passed**。临时文件已删除。

## 4. 主 Agent 正式验证

全部经 `wsl.exe` 在项目目录使用 WSL Miniforge `base`：

| 验证 | 结果 |
|---|---|
| P4A 定向 | **33 passed** |
| 全量 pytest | **642 passed** |
| Ruff | **All checks passed** |
| mypy | **77 source files，0 issues** |

大量 Pandera/Polars deprecation warnings 为既有技术债，不改变本包结果；后续可单独压降，当前不阻塞主业务闭环。
WSL localhost proxy 提示不影响离线测试。本轮未联网、未读 token、未访问 `_old/`、未写 raw/clean/release。

## 5. 最终边界与下一步

P4A 已可作为 P4B 的已验收上游。下一步是 P4B 确定性 BaoStock 跨源 request/journal 与 3000-cell 对账；P4B
通过主验后才能执行 P4C 严格 reader 与不可变发布。B4、G1 和所有 Gate 仍未关闭。
