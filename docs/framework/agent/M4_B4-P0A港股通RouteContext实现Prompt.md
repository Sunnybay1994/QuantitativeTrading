# M4 B4-P0A 港股通 RouteContext 实现 Prompt

角色：全新外部实现 Agent  
模型：`cursor-grok-4.5-high`（非 fast）  
启动条件：R1C source-tree 写会话和其全部 WSL pytest 子进程已经退出

请先完整阅读：

1. `AGENTS.md` 与 `.ai/README.md`、`.ai/coding_rules.md`、`.ai/workflows/multi_agent_delivery.md`
2. `docs/framework/agent/M4_B4港股通Route与日历接口前置裁定.md`
3. `docs/framework/agent/M4_B4-P0A港股通RouteContext领域合同任务单.md`（v2 是唯一实现合同）
4. `docs/framework/agent/M4_B4-P0A港股通RouteContext领域合同独立设计审查报告.md`

设计审查报告中的两个 P0 已由 v2 任务书关闭。立即使用工具按 v2 实现，不要只做计划；若代码事实再次推翻
任务书，停止扩大实现并写证据，不自行发明 identity 或跨入 P0B。

## 环境与范围

Cursor Agent 从 Windows 原生启动，但所有 Python/pytest/Ruff/mypy 命令必须进入 WSL：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base <command>
```

严格遵守任务书文件白名单。禁止修改 B2、P3、TradingConfig、OrderIntent、SymbolMarketState、repository 实现、
数据、历史报告和路线图；禁止初始化 Git。不得调用网络或真实数据。

## 实现目标

- 复用现有 D0 helper 和 envelope，新增 `ConnectRoute`、`VerifiedConnectMarketContext`、两个 build API、窄
  `ConnectMarketContextRepository` Protocol 及包导出；
- 固定向量必须命中任务书给出的 hex；不得建立第二套 JSON/hash helper；
- provenance 保持不透明，不 import backtest/data；`hong_kong_open` 是唯一公开名称；
- P0A 不接入 intent/state/snapshot/B2，不新增 repository 或查询 wrapper，不迁移遗留字符串集合；
- 新增测试只覆盖任务书行为和反例，不锁定无关私有调用顺序。

## 高效验证

先运行任务书列出的 `-k connect_market_context` test node 与定向 Ruff/mypy。只有它们暴露公共回归时才扩大到
`test_execution_contracts.py` / `test_execution_ports.py` 两个文件；禁止全量 pytest、禁止 M3 workflow 测试。
记录每条实际命令、通过/失败/超时和耗时。

## 交付

写入且只写唯一报告：

`docs/framework/agent/M4_B4-P0A港股通RouteContext领域合同交付报告.md`

按 `.ai/task_template.md` 的交付结构记录：结果、文件和目的、标准—证据、实际验证、范围清理、未验证事项与
下一步。不要宣称 B4、M4 或任何 Gate 完成。写完报告即返回压缩摘要。
