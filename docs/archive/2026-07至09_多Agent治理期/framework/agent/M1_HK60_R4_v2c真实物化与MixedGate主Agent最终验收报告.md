# M1 HK60 R4：v2c 真实物化与 Mixed Available-History Gate 主 Agent 最终验收报告

日期：2026-08-15（Asia/Shanghai）  
平台：Windows 原生 Miniforge（本轮按用户指示不实施 Linux/ext4）  
状态：**PASS；关闭 M1 当前 Windows HK60 不复权研究数据闭环**

本结论不把不复权行情冒充正式复权/总回报，不宣称 licensed 港股公司行动、ETF Instrument 系统源、港股 PAPER 或 Linux/ext4 Gate 已完成。

## 1. 前置实现与职责分离

- Mixed-source available-history 实现与三轮外部复验已经完成并合入 `codex/m1-hk60-windows`。
- `06110.HK@2026-06-25` No-Trade 证据的 R4 实现提交为 `11a71f5`；全新外部 `cursor-grok-4.6-high` 会话独立复验 PASS，报告提交为 `15599b5`。
- 主 Agent 将 06110 六个有序提交无冲突 cherry-pick 到集成分支，最终报告提交对应集成 HEAD `cbceed7`。
- 联合主验只运行一次直接相关组合：`test_query.py`、`test_query_universe.py`、`test_hk_history_backfill.py`、`test_schemas.py`，结果 `267 passed, 2 skipped`；八个改动文件 Ruff PASS，四个生产文件 mypy PASS，cold import 与 `git diff --check` PASS。

## 2. UA-M1-005 与新 v2c 身份

按用户对低影响小概率缺行的精确业务裁决，生成且只绑定：

- symbol/date：`06110.HK@2026-06-25`
- source：`USER_APPROVED_MULTI_SOURCE_CONSENSUS`
- source record：`UA-M1-005`
- selector：`user-approved-consensus/ua-m1-005-06110-2026-06-25.record`
- source_as_of：`2026-08-15T09:00:00+00:00`

物化结果：

| 项目 | 结果 |
| --- | --- |
| evidence 数量 | 15 |
| evidence set identity | `1ea6571979ab58f8d3bc5251ea488bae0f5d0c1e2c116c27843773aa23a4dc63` |
| v2c plan identity | `c115e17480467850222bf989b95f52a75966f82a2342fdda1b973c896ce44e49` |
| plan 文件 SHA-256 | `7d64f24122dcd1e97affe21ecae8e83b424509795eb63cb5bdbb80ab047448fe` |
| journal identity | `575c2ddf798182914c08cb558e7e4ce03d17f6a54d18b39e3db87a1f643df693` |
| UA-M1-005 raw SHA-256 | `8f44ca5d7c16a295027c7e04059002451db533272267838ac20699bf6b2c85da` |
| UA-M1-005 metadata SHA-256 | `8b5af49e193b273c5d7f10e52644b92315ce55a85d3c05a06727a0b2fd09819f` |

R4 明确关闭了 UA 身份换源漏洞：任何 `UA-M1-*` record 或 `user-approved-consensus/` selector 都必须绑定 exact USER source；普通非 UA 的 HKEX evidence 行为保持不变。

## 3. 恢复、唯一网络请求与 finalize-v3

新 journal 首次 `--recover-existing-only` 返回 `HK_HISTORY_INCOMPLETE`。逐 request 检查证明前 7 个 receipt 均存在且有效，唯一缺少 request 8：

`4f0a3b266c992bc485f3937fcd79d32c4045dad8e749b45346d35d7f1d2dc85d`

随后执行唯一一次默认回填调用：

```json
{"status":"PASS","network_requests":1,"completed_requests":8,"total_requests":8,"is_complete":true}
```

再次 `--recover-existing-only` 返回 8/8 完整、`network_requests=0`。没有重取前 7 批，也没有第二次网络请求。

以已留存 HKEX `d260710e.htm` 与 canonical metadata 执行唯一一次 `--finalize-v3`：

| 项目 | 结果 |
| --- | --- |
| published rows | 36,361 |
| publication identity | `7c4279e17b530c7c11eef651afe9aa7f39dd9b6b359aa9814d9fd5a45fedc8f7` |
| clean content identity | `8aadea770749009ac02f8f8da3a9f286312a75fad62c2b30d52e7789624a05ba` |
| availability content identity | `c08ebfa259240075c419225af1957e0280443ab5d0fe7b48d013db7b76171106` |
| HKEX retained bundle | `8c6fae2fb99b43ed32ae5450119685f20b353442c69ea60489b6691c591b1426` |

## 4. SH/SZ Mixed Gate

两个 Route 均使用：

- market `as_of=2026-07-10`
- explicit `verification_as_of=2026-08-16T00:00:00+00:00`
- observations `60`
- `--from-verified-hk-availability`
- `--require-available-history`

每次 CLI 内部均 fresh 加载 `VerifiedHkBarBundle`，按 availability 选择唯一 source，并在输出前再次 fresh verify。

| 指标 | SH_CONNECT | SZ_CONNECT |
| --- | ---: | ---: |
| eligible | 644 | 644 |
| required STOCK | 613 | 613 |
| excluded ETF | 31 | 31 |
| rows | 36,361 | 36,361 |
| Tushare rows | 36,360 | 36,360 |
| HKEX rows | 1 | 1 |
| missing sessions | 0 | 0 |
| unexpected sessions | 0 | 0 |
| exempted No-Trade sessions | 15 | 15 |
| available-history complete | true | true |

两份输出内容相同（该日两个 Route 的成员集合均为 644），SHA-256 均为：

`74ab472314be54bea12152ba46bff93388dc90c25ec0d118da53e901498a3846`

## 5. 结论与边界

M1 当前 Windows 研究数据目标已闭合：A 股/ETF 主闭环、双 Route 历史 universe、五日自然调度、HK60 mixed-source 不复权行情、可用历史精确审计均有真实产物和可重现证据。

保留为未来港股 formal/第二波工作的事项：licensed 公司行动 provenance、复权/总回报链、港股 ETF Instrument 系统源以及港股 PAPER。它们不得反向否定本次不复权研究数据闭环，也不得被本报告冒充为已完成。
