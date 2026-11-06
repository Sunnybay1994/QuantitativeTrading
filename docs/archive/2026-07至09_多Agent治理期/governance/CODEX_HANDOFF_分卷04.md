
- Git 已存在有效 HEAD：`master@ed77978`。后续不得再执行 `git init`；当前未提交改动属于正在进行的
  里程碑工作，提交前须按白名单核对，不得覆盖用户或其他 Agent 改动。
- README 链接了根目录 `karpathy-guidelines.md`，但当前文件实际缺失；现行代码规则在
  [`.ai/coding_rules.md`](../ai_通用Agent操作系统/coding_rules.md)。迁移后应决定恢复该文件或修正引用，避免断链。
- 当前约有 94 个生产 Python 文件、63 个测试文件。`data/` 约 15MB，`artifacts/` 约 2MB。
- `archive/legacy_pre_greenfield/` 约 11GB，其中几乎全部是
  `archive/legacy_pre_greenfield/data/qlib_dataset`。生产代码明确不使用该目录，`data/qlib/` 当前为空；迁移时
  可将该 11GB 目录继续压缩/单独冷存或不随工作目录复制，但不要在未备份时删除。
- 移动目录可能改变真实路径、inode、symlink 祖先和 trusted-root 检查。复制完成后不要直接继续写 run state，
  先执行第 6.3 节零网络检查；失败时保留旧目录，禁止修改 receipt 绕过门禁。

## 6. 测试命令及当前结果

### 6.1 验证原则

日常只跑改动相关测试、定向 Ruff/mypy 和最小真实样本。全量 pytest 只在跨模块合流、关键发布、里程碑或
Gate 主验运行。本停止点没有为纯数据发布机械重跑全量测试。

### 6.2 最近已确认结果

| 范围 | 最近结果 |
| --- | --- |
| SSE-REAL1 主验 | SH/SZ reverse audit 两条命令均 exit 0，分别 `644/1212/268/PASS`、`644/1237/417/PASS` |
| SSE-REAL2 主验 | 双 Route `--dry-run` exit 0；SH `1062/919/644/PASS`，SZ `1149/1014/644/PASS`，`published=false` |
| M4 Route/D1-R | 113 passed；五个相关模块 mypy 通过 |
| M3 HISTORY H1–H3 | 197 passed / 1 deselected；Ruff/mypy 通过 |
| M3 HISTORY H4 | 8 个核心预算/CLI 测试通过；定向 Ruff/mypy 通过 |
| M3 G1-P4C 当时全量基线 | 798 passed；Ruff；79 个 source files mypy 通过 |
| Qlib 环境探针 | py312 41 passed / 1 deselected；base 42 passed；Qlib 0.9.7 关键 import/readiness 通过 |

`798 passed` 是 P4C 当时的全量基线，之后还有 Route、HISTORY、SSE 等增量，因此**不能表述为当前 HEAD 的
最新全量回归**。迁移后先跑定向 smoke；在恢复大规模 HISTORY 前通常不必跑全量，在正式 G1 release 或跨
Gate 验收前再跑。

### 6.3 迁移后的零网络 smoke

在新目录中进入 WSL Miniforge base，先运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python --version
/home/mabw/miniforge3/bin/conda run -n base python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status

/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.audit_connect_eligibility \
  --route SZ_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2016-12-05 --expected-baseline-count 417

/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2014-11-17 --mode reverse-audit \
  --snapshot-date 2026-07-10 --expected-baseline-count 268 --dry-run
/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2016-12-05 --mode reverse-audit \
  --snapshot-date 2026-07-10 --expected-baseline-count 417 --dry-run
```

这些命令不得联网或写 data。任何 identity、path、receipt、Schema 或计数差异都先停止调查。

推荐定向测试：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_audit_connect_eligibility.py \
  tests/unit/test_rebuild_connect_universe.py \
  tests/unit/test_eligibility.py \
  tests/unit/test_update_connect.py -q

/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_g1_planning.py \
  tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_candidate.py \
  tests/unit/test_m3_g1_workflow.py \
  tests/unit/test_m3_run_g1.py -q

/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_execution_contracts.py \
  tests/unit/test_execution_ports.py \
  tests/unit/test_execution_store.py \
  tests/unit/test_execution_oms.py \
  tests/unit/test_connect_execution.py \
  tests/unit/test_pretrade_risk.py -q
```

需要全量 Gate 时才使用：

```bash
/home/mabw/miniforge3/bin/conda run -n base ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base mypy src
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
```

## 7. 环境变量和启动方式

### 7.1 运行环境

- 只支持 WSL，不要求兼容 Windows 原生 Python。
- 主体环境：WSL Miniforge `base`；最后验收记录为 Python 3.13.13。
- Qlib 环境：WSL Miniforge `py312`；Python 3.12.13，`pyqlib==0.9.7`。
- 非交互固定前缀：`/home/mabw/miniforge3/bin/conda run -n <env> <command>`。
- 外部 `cursor-agent` 只能从 Windows 启动，但 Prompt 必须要求其在 WSL 新项目路径执行所有 Python、测试和工具。

安装/恢复：

```bash
cd /新的/WSL/项目路径
/home/mabw/miniforge3/bin/conda run -n base python -m pip install -e '.[dev]'
/home/mabw/miniforge3/bin/conda run -n base python -m pip install -e '.[data]'
/home/mabw/miniforge3/bin/conda run -n base python -m pip install -e '.[research]'
```

不要在 base 安装 `.[qlib]`；`py312` 已有已验收 Qlib 环境，迁移代码后只需从新目录调用。

### 7.2 凭据和环境变量

- Tushare token 只在 `configs/tushare.local.toml`。该文件不入 Git，迁移时用私密方式单独复制。
- 可选环境变量 `QUANT_TUSHARE_CONFIG=/安全路径/tushare.local.toml` 用于改变本地配置路径。
- 不支持 `--token` 命令行参数，不把 token 写入 `.env`、MCP URL、日志、报告或聊天。
- 当前不需要其他强制环境变量。交易配置来自 `configs/trading/example.toml`；`auto_trade=false`，无 LIVE。

### 7.3 常用入口

```bash
# M3 状态/分阶段工作流
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status

# 数据更新（真实网络；必须有单独授权和小范围预算）
python -m quant.data.update --source tushare --date YYYY-MM-DD --symbols 000001.SZ

# Tushare 脱敏权限检查
python -m quant.data.check_tushare --date 2026-07-10
```

迁移需保留 `data/raw`、`data/clean`、`data/run_state` 和必要 `artifacts` 的相对结构。不要只复制源码后重建
run state；这会丢失 INDEX/HISTORY receipt 和真实数据血缘。`configs/tushare.local.toml` 因被忽略，普通源码
复制工具可能漏掉，必须单独确认。

## 8. 不应重复尝试的失败方案

1. **不要在 base/Python 3.13 源码硬装 Qlib，也不要降级 base。** 使用已验收 `py312`。
2. **不要让 Qlib LocalProvider 直接挂项目 clean Parquet。** 走 staging + 官方 `dump_bin.py`。
3. **不要把当前港股通名单回填过去。** 必须用 verified snapshot/event 和历史有效区间。
4. **不要恢复 SSE 旧 `ADJUST_TYPE == "01"` 映射。** 官方值是“调进/调出”；错误版本曾把 1,212 行全部变成 REMOVE。
5. **不要用普通 upsert 修复错误 SH clean。** 错误旧行不会被删除；本次已用显式 single-route replace 正确修复。
6. **不要重跑旧 HISTORY 月窗 `suspend_d` 计划。** 它在 5,000 行边界正确 fail closed；不要改成 `>5000`、
   提高上限、盲目 resume、删除旧 evidence 或把不完整 receipt 当成功。
7. **不要在 `/mnt/g` DrvFS 用 `os.replace`/hardlink 假装正式 G1 no-clobber publish。** 正式 release 要在支持并经
   探针验证的 WSL ext4 路径执行。
8. **不要在没有正式 `VerifiedG1Release` 时启动真实 G2–G9。** fake/contract 测试不能关闭 Gate。
9. **不要把空复权因子静默当作 1。** 明确不复权时使用显式参数；研究收益不能混用不同供应商 HFQ 与现金分红总回报。
10. **不要把网页可访问等同于数据许可。** HKEX 公共网页/JSONP 禁止脚本化生产采集；Tushare ETF/API
    权限以当前官方权限表和有界探针为准，不沿用旧积分数字猜测，也不循环重试。
11. **不要把 AKShare 网页端点当唯一生产源。** 已出现上游拒绝/无效响应；保留 raw、换 BaoStock，并继续质量门禁。
12. **默认运行时仍是 WSL Miniforge base。** 本轮用户明确允许 Windows Miniforge 做兼容性定向验证；
    不得因此把生产运行时、路径或依赖合同改成 Windows-only。
13. **不要让因子/策略/执行层直接扫描 `data/` 或 `archive/`。** 只通过 `quant.data` repository/显式工具消费验证对象。
14. **不要重新初始化 Git、删除 11GB legacy 数据或改 receipt 来适应新路径，除非用户明确授权。** 先保留旧目录和哈希证据。
15. **不要在普通开发返工中机械跑全量 pytest、使用大数据样本或高频轮询长任务。** 当前约束是 usage/效率，不是时间。

## 9. 下一步建议

### 9.1 已完成目录定位

1. Windows `F:\AI_Coding\QuantitativeTrading` 与 WSL
   `/home/mabw/AI_Coding_win/QuantitativeTrading` 已确认解析到同一目录；后续不再按旧 `/mnt/g` 路径执行。
2. `configs/tushare.local.toml` 继续保持本地 ignored 且不得输出 token。
3. Git 已有 `master@ed77978`；继续用 `git status`、diff、hash 和测试报告审计变更，不执行第二次初始化。
4. `archive/legacy_pre_greenfield/` 不参与生产或普通测试，未经单独授权不删除。

### 9.2 恢复 M3 主线

HISTORY receipts 已完成，但 HISTORY stage 尚未通过：

1. 先由全新外部只读会话独立初验 R5 最小 fixture；通过后主验两个 resume 测试和定向静态检查。
2. 对正式 `G1_CANDIDATE_COMPONENT_INVALID` 做零网络组件级定位。基金 mapper 已排除，优先逐层验证股票
   daily/adj_factor、严格复权覆盖、stk_limit/suspend、公司行动选择/对账和最终 Schema；避免每次只重复
   20–35 分钟 full build 而无细分证据。
3. 若发现实现缺陷，先冻结返工任务书，再走全新 Cursor 实现、另一全新 Cursor 独立初验、主 Agent 终验；
   若是正式数据缺陷，保留 raw 并按既有 fail-closed 合同裁定，禁止改 receipt 或静默填充。
4. full candidate/HISTORY 真正通过后才运行 REFERENCE 和 PREPARE。正式 PUBLISH 还需用户启用主机虚拟化
   并提供经探针验证的 WSL2 ext4 root，取得 `VerifiedG1Release` 后方可启动真实 G2A。
5. 再按 `G2A→G2B→G2C→G3A→G3B→G4…→G9` 的任务书顺序推进 Qlib provider、标签、模型、回测、追踪和 Gate。

### 9.3 M4 与其他补项

- M3 G7 前置满足后推进 M4 B1/B3，再完成 B4/B5、统一回测 B6–B8。
- 完成 P2 Paper Gateway、P4 outbox 服务、P5 对账恢复、P6–P8 操作和四周稳定性 Gate。
- P1 两代码 60 日有界探针已通过；实现并验证 HK60 raw-first 可恢复 manifest 后，按最多 83 只/批、至少
  60 分钟冷却逐批执行。不得调用 HKEX 公共网页/JSONP；`02983.HK` 缺行必须使用合规来源或明确契约
  处理，不能伪造。
- 券商权限和程序化交易报备明确前不实现 LIVE Gateway；最终实盘前轮换 Tushare token。

路径定位已完成；后续任何 path/trusted-root smoke 差异仍应保留证据并 fail closed，不通过修改合同迁就。
