# M3 G1-P4B 跨源证据交付报告

日期：2026-07-14  
角色：外部实现 Agent（非独立初验）  
实际模型标识：`cursor-grok-4.5-high`  
任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)  
主设计：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §2、§3、§5、§7–§9  
前置：[`M3_G1_P4A主Agent最终验收报告.md`](M3_G1_P4A主Agent最终验收报告.md)  
状态：**待独立初验/待主验**（本轮因任务书与现行权威代码不可同时满足而停止扩大实现；**未宣称** B4 / G1 / M3 / Gate 通过）

## 1. 本轮结论

按 `AGENTS.md` §11 与任务书要求：发现任务书与现行权威代码的真实矛盾后，**停止扩大实现**，提交最小证据，等待主 Agent 修订权威契约后再继续 P4B。

本轮**未新增** `m3_reference.py`、未改 connector/`__init__.py`、未写 P4B 测试套件；工作树既有用户/主 Agent 改动保留。

## 2. 阻塞矛盾（最小证据）

### 2.1 现象

任务书 §7.9 要求 reconciliation `issues` 只允许：

- `CROSS_SOURCE_INCOMPLETE`
- `CROSS_SOURCE_MISMATCH`

且均为 ERROR，类型为 P4A 导出的 `G1QualityIssue`，并进入
`CrossSourceReconciliationBundle.issues: tuple[G1QualityIssue, ...]`。

现行已验收 P4A 代码中，`G1QualityIssue.__post_init__` 仅接受
`src/quant/data/m3_g1_candidate.py` 内 `_ISSUE_CODES`；该集合**不含**上述两个
`CROSS_SOURCE_*` 码。构造任一码立即失败。

### 2.2 根因

P4A 有意把 primary-audit issue 码与跨源码隔离：独立初验报告写明
「无 `CROSS_SOURCE_*`；构造 `CROSS_SOURCE_MISMATCH` 被拒绝」为通过项。  
SSOT [`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10 的首版 issue 全集又包含这两个码。  
P4B 任务书要求复用同一 `G1QualityIssue`，同时禁止修改 `m3_g1_candidate.py`。

三者无法同时满足。

### 2.3 应遵循规则

- `AGENTS.md` §11：实现 Agent 发现任务书矛盾时停止扩大实现并提交证据，由主 Agent 先改权威契约。  
- 任务书 §2：不得修改 `m3_g1_candidate.py` 迁就实现。  
- 任务书 §7.9 / 主设计 §5.6：issues 必须是带 `CROSS_SOURCE_*` 的 `G1QualityIssue`。

### 2.4 最小复现（WSL Miniforge `base`，零网络）

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -c "
from quant.data.m3_g1_candidate import G1QualityIssue, _ISSUE_CODES
print('INCOMPLETE', 'CROSS_SOURCE_INCOMPLETE' in _ISSUE_CODES)
print('MISMATCH', 'CROSS_SOURCE_MISMATCH' in _ISSUE_CODES)
for code in ('CROSS_SOURCE_INCOMPLETE', 'CROSS_SOURCE_MISMATCH'):
    try:
        G1QualityIssue(code=code, severity='ERROR', message='probe', count=1, evidence=())
        print(code, 'OK')
    except Exception as e:
        print(code, type(e).__name__, str(e))
"
```

实测输出：

```text
INCOMPLETE False
MISMATCH False
CROSS_SOURCE_INCOMPLETE ValueError G1QualityIssue code 非法
CROSS_SOURCE_MISMATCH ValueError G1QualityIssue code 非法
```

权威位置：

```113:137:src/quant/data/m3_g1_candidate.py
_ISSUE_CODES = frozenset(
    {
        "REQUEST_PLAN_MISMATCH",
        ...
        "CORPORATE_ACTION_FACTOR_MISMATCH",
    }
)
```

（集合止于主源码，无 `CROSS_SOURCE_*`。）

### 2.5 实现者未自行猜测的绕过（故未实施）

以下均会破坏冻结边界，本轮明确拒绝：

1. 修改 `m3_g1_candidate.py` 的 `_ISSUE_CODES`（任务书禁止）；  
2. 在 `m3_reference.py` 另造平行 issue 类型（违反 §7.9 / bundle 字段合同）；  
3. 运行时 monkeypatch `_ISSUE_CODES`（静默改上游合同，不可审计）；  
4. 弱化测试、省略 issues、或把跨源问题改成主源码（迁就合同）。

### 2.6 建议主 Agent 决策（实现者不改 SSOT）

最小且与 SSOT §4.10 一致的修复方向：在允许文件中扩展 P4A `G1QualityIssue` 允许码，加入
`CROSS_SOURCE_INCOMPLETE` / `CROSS_SOURCE_MISMATCH`；并同步修订 P4A「构造跨源码必须拒绝」的测试期望，
或在任务书中明确该扩展属于 P4B 允许对 `m3_g1_candidate.py` 的唯一外科式改动。  
确认后重新下发实现任务，再进入外部实现 → 独立初验闭环。

## 3. 修改文件清单

| 文件 | 变更 |
|---|---|
| `docs/M3_G1_P4B跨源证据交付报告.md` | **本报告**（唯一本轮写入） |

未修改：`m3_reference.py`（未创建）、`baostock.py`、`data/__init__.py`、P4B 测试、路线图、Gate、上游算法。

## 4. 任务书逐项映射（本轮）

| 任务书项 | 状态 |
|---|---|
| §1 四件事（抽样 / journal / 闭包 / 3000-cell） | **未实现**（阻塞） |
| §2 允许文件实施 | 未改生产代码；仅本报告 |
| §3 executor 签名含 sample_plan | 未实现 |
| §4 公共类型与五函数导出 | 未实现 |
| §5 身份自证 | 未实现 |
| §6 connector + journal 状态机 | 未实现 |
| §7 reconciliation（含 CROSS_SOURCE issues） | **合同冲突，无法按现行代码实现** |
| §8 必测矩阵 | 未写测试 |
| §9 定向/全量 pytest、Ruff、mypy | 未跑实现验收（无实现体）；仅跑上述最小复现 |

## 5. 验证、联网与环境

- 环境：Windows `cursor-agent` 启动；Python 经 `wsl.exe` +
  `/home/mabw/miniforge3/bin/conda run -n base`。  
- 本轮未联网、未读 token / `_old/`、未写 raw/journal/release。  
- 未宣布独立初验通过；本报告**不可**作为初验替代。

## 6. 未验证项与已知限制

- P4B 全部功能与 §8 测试矩阵未验证。  
- P4C 未开始。  
- 阻塞解除前不具备「可交独立初验」的实现交付物。

## 7. 交付声明

本轮交付仅为：**合同矛盾证据 + 本报告**。  
状态固定为「待独立初验/待主验」语义下的**实现阻塞回报**；请主 Agent 修订权威契约后重开外部实现会话。  
不宣称 B4 / G1 / M3 / 任一 Gate 通过。
