# 外部下一波并行包 I/O 冲突矩阵

日期：2026-07-17  
性质：**只读设计/调度裁定；供总协调直接派发；不是授权，不得勾选 Gate/路线图**  
假设：**INDEX 独立复验已通过**；**用户尚未授权 HISTORY**  
依据：`M3_M4后续外部总执行任务书.md` §2.2/§5/§6/§7/§9；`外部Agent并发调度台账.md`；P0A/P0B 任务单白名单；G1 R1C 真实运行写路径摘要

---

## 1. 结论摘要

1. INDEX 复验通过后，**先**做协调侧零网络 `status` + 资源清单更新（仅 docs/读 data），**禁止**启动 HISTORY。  
2. 当前窗口主线：**P0A 实现 → P0A 独立初验**（二者不可并行）；通过后才 **P0B1→P0B2→P0B3** 严格串行。  
3. 若用户**突然授权 HISTORY**：与任何 `src/**` 写会话 **I/O/身份冻结冲突**（单数据写者 + G1 可能捕获 source-tree identity），须串行让路。  
4. G1/G9/任何捕获 source-tree identity 的命令运行期间：**冻结全部** `src/**`、`tests/**`、`configs/**` 写会话。  
5. M4-1的 B1∥B3：**前置未满足（需 G7），仅预裁定**——仅当文件白名单完全互斥（尤其 `costs.py` 不能双写）才可并行。

---

## 2. 分类说明（裁定用）

| 代码 | 含义 |
|---|---|
| **A** | **依赖阻塞**：即使文件不冲突也不能并行（前置未通过、实现者≠验收者、合同面必须先稳定） |
| **B** | **I/O 冲突阻塞**：同生产/测试/报告路径、同 `data/**` 写者、或同 identity 捕获窗口 |
| **C** | **可并行**：白名单、测试、报告路径、data、identity 窗口**全部互斥**，且无 A 类依赖 |

---

## 3. 包对裁定表

| 包对 | 依赖？(A) | I/O冲突？(B) | 可否并行 | 理由 |
|---|---|---|---|---|
| **Coord：零网络 status + 资源清单更新** vs **任何新建 `src/**` 写会话** | 弱序：建议先完成 status 冻结 `S`/请求数 | 若 status **不**捕获 source-tree identity：无生产文件冲突；仅 docs 与只读 data | **建议串行（status 先）** | 总任务书 §4/§6.1：复验通过后先 status+清单，再进入 M4队列。status 快、风险低；避免与后续写会话争抢台账注意力。 |
| **P0A 实现** vs **P0A 独立初验** | **A 是**：实现者≠验收者；须先交付再验收 | **B 是**：同一报告链（交付→初验）；验收不得读正在被写的白名单文件 | **否** | §2.1/§6.2；初验报告固定 `M4_B4-P0A…独立初验报告.md`。 |
| **P0A（实现或初验）** vs **HISTORY（若突然授权）** | 无直接功能依赖（P0A 不需 HISTORY；HISTORY 不需 P0A） | **B 是**：(1) HISTORY 独占 `data/raw/m3_g1/**`、`data/run_state/m3_g1/**` 单写者；(2) G1 真实阶段可能捕获 source context/identity → **冻结全部 `src/**`/`tests/**`/`configs/**` 写入**；(3) P0A 写 `enums/contracts/ports`+测试，落在冻结窗口内 | **否** | §2.2、§7.1；G1 任务单真实运行写路径。若 HISTORY 被授权：**先停/不启 P0A 写会话**，或等 P0A 闭环完全结束再启 HISTORY。 |
| **Coord status/清单** vs **HISTORY** | **A 是**：HISTORY 前置要求已冻结真实 `S` 与计划请求数 | **B 若并发**：同 data 布局读写窗口 + 同类授权清单报告链 | **否**（且当前未授权） | §7.1；清单只生成授权建议，**不等于**可启 HISTORY。 |
| **P0B1** vs **P0B2** | **A 是**：P0B2 前置 = P0B1 独立初验通过 | 白名单主体互斥（contracts vs `connect_execution`），但合同面未稳定时仍禁并 | **否** | P0B 任务单：前一子包初验未通过不得启后一；B2 必须消费已迁移的 intent/snapshot 合同。 |
| **P0B2** vs **P0B3** | **A 是**：P0B3 前置 = P0B2 初验通过 | 白名单互斥（B2 vs `risk.py`），依赖仍强制串行 | **否** | P3 须在 B2 已消费唯一 RouteContext 之后做 route-aware 风控。 |
| **P0B1** vs **P0B3** | **A 是**（经 P0B2 链） | 白名单互斥，但不得跳过 P0B2 | **否** | 严格 P0B1→P0B2→P0B3；禁止跳步。 |
| **P0A** vs **P0B1** | **A 是**：P0B1 前置 = P0A 外部独立初验通过 | **B 亦是**：共享 `contracts.py` / `__init__.py` / `test_execution_contracts.py`（P0B1 迁移 intent/state/snapshot） | **否** | §6.3；P0A 禁止提前改 OrderIntent/SymbolMarketState。 |
| **P0A/任何 `src/**` 写** vs **G1 identity 捕获窗口**（含 HISTORY/G9/明确捕获 source-tree 的命令） | 可无功能依赖 | **B 是**：全局冻结 `src/**`、`tests/**`、`configs/**` 写入 | **否** | §2.2；台账：INDEX/长测试/复验期间不启 P0A。窗口结束后才可派发写会话。 |
| **P0A 实现** vs **Coord 总报告/台账更新** | 无 | 报告路径不同（P0A 交付报告 vs 总报告/台账） | **C 可**（仅 docs） | 协调只写台账/总报；不触 `src/`。注：不得与 P0A **同一**交付/初验报告路径双写。 |
| **P0B任一子包** vs **HISTORY** | 无直接功能依赖 | **B 是**（同上：identity 冻结 + 单 data 写者） | **否** | 与 P0A×HISTORY 同理。 |
| **M4-1 B1** vs **M4-1 B3** | **A 当前是**：需 G7 外部独立初验通过（**前置未满足**） | **预裁定 B：若两者同时写 `backtest/costs.py` 则冲突** | **仅预裁定：前置满足且白名单完全互斥时为 C** | 总任务书 §9：「文件白名单互斥，可并行」。M4 分包书：B1 触 `a_share_execution.py`+可能 `costs.py`；B3 扩 `costs.py`+新 `fx.py`。**互斥条件**：B1 写会话不改 `costs.py`（仅调用 G7 纯函数），B3 独占 `costs.py`/`fx.py`；测试与报告路径各自独占。**当前不得派发**。 |
| **M4-1 B1/B3** vs **P0A/P0B** | **A 是**（B1/B3 等 G7；且 B4 等 B1/B3，与 P0 链无直接启动关系但波次更晚） | B1 与 P0B2 可能近邻 `backtest/`，须单独核对；**当前前置未满** | **当前不派发** | §6 结束条：HISTORY 未授权则停止新增代码任务（P0 闭环后）；不得绕过 G7 启 B1/B3。 |

### G1 R1C 关键节点写路径摘要（只读）

| 阶段 | 允许写入（摘要） | 与当前窗口关系 |
|---|---|---|
| **status（零网络）** | 不写 raw；协调更新资源清单/docs | INDEX 复验后立即执行 |
| **HISTORY** | `data/raw/m3_g1/**`、`data/run_state/m3_g1/**` + 真实运行交付/复验报告 | **未授权**；与任何 `src/**` 写会话互斥 |
| **REFERENCE** | 同上 data 布局（BaoStock） | 更后；单写者 |
| **PUBLISH** | `data/clean/m3_g1/releases/**`（仅 RENAME_NOREPLACE） | 硬门禁；与本波无关 |
| **P0A** | `domain/enums.py`、`execution/contracts.py`、`ports.py` 及导出、对应 unit tests、P0A 交付报告 | INDEX 闭环+无 identity 冻结后可启 |
| **P0B1/2/3** | 见各子包白名单；报告路径各自独占 | 严格串行 |

---

## 4. 推荐派发顺序（INDEX 通过后 → HISTORY 授权前）

```text
1. [协调/只读] 零网络 status → 冻结 S、history_requests、evidence/磁盘摘要
   → 更新 M3_G1_R1C-B真实运行授权与资源清单.md + 总报告/台账
   → 仅生成 HISTORY 授权建议；禁止启 HISTORY

2. [代码写] M4 B4-P0A 实现（现行 Prompt/任务单白名单）

3. [代码只读] P0A 独立初验（新上下文；唯一初验报告路径）
   — 失败则返工→复验循环；不启 P0B

4. [串行] P0B1 实现→初验 → P0B2 实现→初验 → P0B3 实现→初验
   （每子包实现者≠验收者；三包合流后可一次 D0+B2+P3 定向合流）

5. [停止点] 若 HISTORY 仍未授权：停止新增代码任务，提交阶段总报告
   — 不启 G2+、不启 M4-1 B1/B3、不启 B4/P2

并行窗口（本波实际可用）：
  - 仅「协调 docs 更新」可与「已结束的只读验收之后的另一只读会话」在报告路径互斥时重叠
  - **不存在** P0A∥P0B、P0B子包互并、P0A∥HISTORY、B1∥B3（前置未满）

若 HISTORY 突然授权：
  - 立即检查是否存在活跃 `src/**` 写会话
  - 有则：等其闭环结束，或暂停写会话后再启单一 HISTORY 数据写会话
  - HISTORY 期间不启任何新的 `src/**`/`tests/**`/`configs/**` 写会话
```

---

## 5. 明确声明（非授权）

- **不得**因本文件勾选任何 Gate、路线图或宣称 M3/M4/G1 完成。  
- **本文件不是授权**：不授权 HISTORY/REFERENCE/PREPARE/PUBLISH，不放宽 data/身份/原子发布合同。  
- 外部报告仅可写「外部闭环通过、待主 Agent 整体验收」。  
- 派发前仍须在 `docs/agent/外部Agent并发调度台账.md` 登记会话角色、模型、白名单与互斥原因。
