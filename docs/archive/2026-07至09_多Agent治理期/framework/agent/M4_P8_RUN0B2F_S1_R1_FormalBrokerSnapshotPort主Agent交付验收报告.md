# M4 P8 RUN-0B2F-S1 R1：Formal Broker Snapshot Port 主 Agent 交付验收报告

日期：2026-08-12  
结论：**PASS（Windows 只读工程合同）；formal gateway dispatch 未实现并等待 UA-M4-003**

## 完成内容

- 新增 `paper_formal_broker_snapshot.py`，只公开稳定错误与 port opener。
- opener 与每次 query 均 fresh 调用 B2E existing verifier；必须返回传入同一 exact capability，之后才取得其受控 store。
- query 复用 actual `DurablePaperBrokerSnapshotPort` 重建 `VerifiedBrokerEvidence`；不接受 caller path、descriptor、snapshot 或 evidence。
- wrong gateway、hostile fresh verifier、closed/stale/forged capability 统一稳定脱敏失败。
- durable snapshot 实现延迟到 query 才加载；模块冷导入不加载 service/CLI/soak/reporting、研究重依赖或外部 broker SDK。
- 未提供 submit/cancel/open gateway，不接收 clock/fill/fault，不写 store 或 OMS。

## 验证

```text
B2E + formal snapshot focused
8 passed in 8.57s

formal snapshot + B1 store + B1 durable gateway adjacency
33 passed in 33.14s

Ruff: PASS
mypy: PASS
cold import/export: RUN0B2F_S1_COLD_PASS
scoped diff-check: PASS
```

## 变更范围

- `src/quant/execution/paper_formal_broker_snapshot.py`
- `src/quant/execution/__init__.py`（lazy export）
- `tests/unit/test_paper_formal_broker_store.py`
- 任务单与本报告

未修改 B1 schema、formal store、runtime/policy/binding/account 生产合同、gateway dispatch、service、CLI、runner、soak 或正式数据目录。

## 剩余边界

- UA-M4-003 未批示前，不得把测试 `_Clock/_Policy/_Faults` 或任何猜测的全成/零成交规则装入 formal gateway。
- 当前没有 Linux/ext4 Gate 证据，也没有授权 PAPER 正式运行。
