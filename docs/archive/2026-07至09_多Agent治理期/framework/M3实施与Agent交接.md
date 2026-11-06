# M3 Qlib/LightGBM 实施与 Agent 交接

正文按原顺序分卷，内容完整保留；本文件继续作为原链接入口。

- [分卷 1](M3实施与Agent交接_分卷01.md)
- [分卷 2](M3实施与Agent交接_分卷02.md)
- [分卷 3](M3实施与Agent交接_分卷03.md)
- [分卷 4](M3实施与Agent交接_分卷04.md)
- [分卷 5](M3实施与Agent交接_分卷05.md)
- [分卷 6](M3实施与Agent交接_分卷06.md)
- [分卷 7](M3实施与Agent交接_分卷07.md)
- [分卷 8](M3实施与Agent交接_分卷08.md)
- [分卷 9](M3实施与Agent交接_分卷09.md)
- [分卷 10](M3实施与Agent交接_分卷10.md)
- [分卷 11](M3实施与Agent交接_分卷11.md)

## 原章节导航

# M3 Qlib/LightGBM 实施与 Agent 交接

[阅读正文](M3实施与Agent交接_分卷01.md)

## 1. 本阶段要交付什么

[阅读正文](M3实施与Agent交接_分卷01.md)

## 2. 已冻结的架构决策

[阅读正文](M3实施与Agent交接_分卷01.md)

### 2.1 Qlib 的位置

[阅读正文](M3实施与Agent交接_分卷01.md)

### 2.2 数据和标签

[阅读正文](M3实施与Agent交接_分卷01.md)

### 2.3 复权与字段

[阅读正文](M3实施与Agent交接_分卷01.md)

### 2.4 可复现性

[阅读正文](M3实施与Agent交接_分卷01.md)

### 2.5 MLflow

[阅读正文](M3实施与Agent交接_分卷01.md)

## 3. 稳定目录与模块边界

[阅读正文](M3实施与Agent交接_分卷01.md)

## 4. 函数级接口

[阅读正文](M3实施与Agent交接_分卷01.md)

### 4.0 `config.py`

[阅读正文](M3实施与Agent交接_分卷01.md)

#### 4.0.1 字段、类型与 selector 闭包

[阅读正文](M3实施与Agent交接_分卷01.md)

#### 4.0.2 规范 hash 与 URI

[阅读正文](M3实施与Agent交接_分卷02.md)

#### 4.0.3 错误与不可变对象

[阅读正文](M3实施与Agent交接_分卷02.md)

#### 4.0.4 凭据、路径与 URI 的机械规则

[阅读正文](M3实施与Agent交接_分卷02.md)

### 4.1 `readiness.py`

[阅读正文](M3实施与Agent交接_分卷02.md)

### 4.2 `snapshot.py`、`provider.py` 与 provider contracts

[阅读正文](M3实施与Agent交接_分卷02.md)

### 4.3 `labels.py`

[阅读正文](M3实施与Agent交接_分卷03.md)

### 4.4 `folds.py`

[阅读正文](M3实施与Agent交接_分卷04.md)

### 4.5 `features.py`、`alignment.py` 与 `qlib_adapter.py`

[阅读正文](M3实施与Agent交接_分卷04.md)

### 4.6 `model.py`

[阅读正文](M3实施与Agent交接_分卷04.md)

### 4.7 `evaluate.py`

[阅读正文](M3实施与Agent交接_分卷05.md)

### 4.8 `ml_topk.py`

[阅读正文](M3实施与Agent交接_分卷05.md)

### 4.9 `tracking.py` 和 `run_m3.py`

[阅读正文](M3实施与Agent交接_分卷05.md)

### 4.9.1 `quality_gate.py` 和 `acceptance.py`

[阅读正文](M3实施与Agent交接_分卷07.md)

### 4.10 `index_membership.py` 和 `m3_backfill.py`

[阅读正文](M3实施与Agent交接_分卷07.md)

### 4.11 `a_share_simulator.py`：G7 统一 A 股回测

[阅读正文](M3实施与Agent交接_分卷09.md)

## 5. 可直接交给另一个 Agent 的任务包

[阅读正文](M3实施与Agent交接_分卷10.md)

### D1：运行时就绪审计（历史标题曾含“配置加载”）

[阅读正文](M3实施与Agent交接_分卷10.md)

### D2：交易日 fold 与 embargo

[阅读正文](M3实施与Agent交接_分卷10.md)

### D3：独立标签计算

[阅读正文](M3实施与Agent交接_分卷10.md)

### D4：确定性 staging 与 manifest

[阅读正文](M3实施与Agent交接_分卷10.md)

### D5：预测指标

[阅读正文](M3实施与Agent交接_分卷10.md)

### D6：分数标准化与无状态 Top-k

[阅读正文](M3实施与Agent交接_分卷10.md)

### D7：MLflow 薄适配器

[阅读正文](M3实施与Agent交接_分卷10.md)

### D8：固定版本 Qlib dump 工具获取器

[阅读正文](M3实施与Agent交接_分卷10.md)

## 6. 主 Agent 决策与未关闭门禁

[阅读正文](M3实施与Agent交接_分卷10.md)

### 6.1 G0：Qlib/Python 兼容

[阅读正文](M3实施与Agent交接_分卷10.md)

### 6.2 Qlib dump 工具供应链（决策已完成）

[阅读正文](M3实施与Agent交接_分卷10.md)

### 6.3 G1：本地数据审计

[阅读正文](M3实施与Agent交接_分卷10.md)

### 6.4 G1：Tushare 2000 积分取数计划

[阅读正文](M3实施与Agent交接_分卷10.md)

### 6.5 G2–G3：Alpha158 与标签语义（决策已完成，待真实环境验证）

[阅读正文](M3实施与Agent交接_分卷11.md)

### 6.6 G5–G6：模型与预测证据

[阅读正文](M3实施与Agent交接_分卷11.md)

### 6.7 G7：组合与统一 A 股回测

[阅读正文](M3实施与Agent交接_分卷11.md)

### 6.8 G8：产物与 MLflow 证据链

[阅读正文](M3实施与Agent交接_分卷11.md)

### 6.9 尚未关闭的外部门禁

[阅读正文](M3实施与Agent交接_分卷11.md)

## 7. Agent 提交格式

[阅读正文](M3实施与Agent交接_分卷11.md)

### 7.1 四阶段交付与验收流程

[阅读正文](M3实施与Agent交接_分卷11.md)

### 7.2 问题反馈必须沉淀为规则

[阅读正文](M3实施与Agent交接_分卷11.md)

### 7.3 实现 Agent 提交内容

[阅读正文](M3实施与Agent交接_分卷11.md)

## 8. 主 Agent 验收矩阵

[阅读正文](M3实施与Agent交接_分卷11.md)

## 9. 官方参考

[阅读正文](M3实施与Agent交接_分卷11.md)

