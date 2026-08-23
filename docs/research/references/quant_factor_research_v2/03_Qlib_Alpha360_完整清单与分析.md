
---
title: Qlib Alpha360完整清单与分析
updated: 2026-08-14
source: Microsoft Qlib loader.py
feature_count: 360
---

# Qlib Alpha360：完整清单、逻辑、适用性与失效条件

## 1. 定义

Alpha360由6类原始日频序列各取60个滞后值组成：`CLOSE、OPEN、HIGH、LOW、VWAP、VOLUME`，共`6×60=360`。价格序列均除以**当前收盘价**，成交量序列均除以**当前成交量+epsilon**。官方注释将其定位为“过去60日原始价格与成交量数据”。[Q1]

Alpha360更接近一个固定长度的序列张量，而不是360个相互独立的经济因子。它特别适合GRU/LSTM/TCN/Transformer等时序模型，也可输入树模型；线性模型直接使用时会面临严重共线。

## 2. 六类序列的经济含义

### CLOSE0–CLOSE59

- **定义**：过去收盘/当前收盘。
- **逻辑**：最直接的价格路径；大于1表示过去价格高于当前，原始方向更像回撤/反转坐标。
- **更适合**：数据连续、复权可靠、至少60日历史的股票；原始序列模型在大中盘和流动性较好的股票上更易避免微观噪声。
- **有效环境**：价格/成交路径形状包含信息且训练样本足以学习非线性模式。
- **失效风险**：公司行为处理错误、长期停牌、涨跌停、一字板、当前归一化分母异常、训练域与实盘域风格变化。
### OPEN0–OPEN59

- **定义**：过去开盘/当前收盘。
- **逻辑**：包含隔夜跳空与日内路径；受集合竞价和开盘机制影响。
- **更适合**：数据连续、复权可靠、至少60日历史的股票；原始序列模型在大中盘和流动性较好的股票上更易避免微观噪声。
- **有效环境**：价格/成交路径形状包含信息且训练样本足以学习非线性模式。
- **失效风险**：公司行为处理错误、长期停牌、涨跌停、一字板、当前归一化分母异常、训练域与实盘域风格变化。
### HIGH0–HIGH59

- **定义**：过去最高/当前收盘。
- **逻辑**：记录过去上方极值路径和距高点结构。
- **更适合**：数据连续、复权可靠、至少60日历史的股票；原始序列模型在大中盘和流动性较好的股票上更易避免微观噪声。
- **有效环境**：价格/成交路径形状包含信息且训练样本足以学习非线性模式。
- **失效风险**：公司行为处理错误、长期停牌、涨跌停、一字板、当前归一化分母异常、训练域与实盘域风格变化。
### LOW0–LOW59

- **定义**：过去最低/当前收盘。
- **逻辑**：记录过去下方极值路径和距低点结构。
- **更适合**：数据连续、复权可靠、至少60日历史的股票；原始序列模型在大中盘和流动性较好的股票上更易避免微观噪声。
- **有效环境**：价格/成交路径形状包含信息且训练样本足以学习非线性模式。
- **失效风险**：公司行为处理错误、长期停牌、涨跌停、一字板、当前归一化分母异常、训练域与实盘域风格变化。
### VWAP0–VWAP59

- **定义**：过去VWAP/当前收盘。
- **逻辑**：成交重心路径；适合学习价格压力和均值回归。
- **更适合**：数据连续、复权可靠、至少60日历史的股票；原始序列模型在大中盘和流动性较好的股票上更易避免微观噪声。
- **有效环境**：价格/成交路径形状包含信息且训练样本足以学习非线性模式。
- **失效风险**：公司行为处理错误、长期停牌、涨跌停、一字板、当前归一化分母异常、训练域与实盘域风格变化。
### VOLUME0–VOLUME59

- **定义**：过去成交量/当前成交量。
- **逻辑**：记录相对量能路径；当前量极小时数值不稳。
- **更适合**：数据连续、复权可靠、至少60日历史的股票；原始序列模型在大中盘和流动性较好的股票上更易避免微观噪声。
- **有效环境**：价格/成交路径形状包含信息且训练样本足以学习非线性模式。
- **失效风险**：公司行为处理错误、长期停牌、涨跌停、一字板、当前归一化分母异常、训练域与实盘域风格变化。

## 3. 滞后带解释

| 滞后 | 信息尺度 | 主要信息 | 更适合 | 风险 |
|---:|---|---|---|---|
| 0–4 | 极短期 | 日内形态、隔夜、短反转、异常量 | 高流动性、短持有期 | 成本和微观噪声 |
| 5–19 | 短期 | 两到四周路径、短趋势/回撤 | 活跃大中盘、中盘 | 参数和风格切换 |
| 20–39 | 中期 | 月度趋势、波动与成交状态 | 大中盘、月度模型 | 反应滞后 |
| 40–59 | 中长期 | 季度路径与状态背景 | 成熟、历史稳定股票 | 次新缺失、结构断点 |

## 4. 两个近常数特征

- `CLOSE0 = close/close = 1`，在任何有限、非缺失样本上是严格常数；预处理后通常变为0或NaN，应直接删除。
- `VOLUME0 = volume/(volume+1e-12)`在正常成交日近似1；在零成交日为0，主要编码“是否零成交/停牌”，而非连续量能。若另有交易状态字段，应删除或重新定义。

## 5. 与Alpha158的关系

Alpha360的60日OHLCV/VWAP序列可以确定性计算Alpha158的大部分价量统计，因此两者属于L2“可推导冗余”。但在模型能力受限时，显式提供Alpha158的均值、波动、极值和相关可降低样本复杂度；深度序列模型则可能从Alpha360直接学习路径。

精确重合包括：

- Alpha158 `OPEN0/HIGH0/LOW0/VWAP0` 与Alpha360同名滞后0特征；
- Alpha158 `ROC5/10/20/30` 与Alpha360 `CLOSE5/10/20/30`；
- `ROC60`没有Alpha360精确对应，因为Alpha360最大滞后为59。

## 6. 适用模型

| 模型 | 使用建议 |
|---|---|
| 线性/岭回归 | 删除常数，强正则化；可先做PCA、差分或稀疏选择 |
| LightGBM/XGBoost | 可用，但360个高度相关分裂会稀释重要性；按滞后带和序列块做约束/抽样 |
| MLP | 标准化后可用，但不显式利用时间局部性 |
| GRU/LSTM | 自然适配6×60序列；注意缺失掩码和时间顺序 |
| TCN/1D-CNN | 适合局部形态和多尺度卷积；需避免把特征顺序打乱 |
| Transformer | 可学习长短依赖，但数据需求和过拟合风险最高；应加入位置编码和严格样本外 |

## 7. 股票适用性

- **大中盘高流动性**：路径稳定、停牌少、归一化更可靠，适合深度序列模型。
- **活跃中小盘**：路径Alpha可能更强，但涨跌停、复牌和冲击成本需要进入标签与掩码。
- **微盘/低流动性**：当前成交量归一化会产生极值，模型容易学习“不可交易状态”；应设成交额底线或单建模型。
- **次新股**：不足60日无法形成完整序列；不要用未来填充或全样本均值填充。
- **行业特殊股票**：金融、地产等不影响纯价量定义，但模型可能学习行业暴露，需在标签/组合层做行业约束。

## 8. 全量360特征清单

| 特征 | 滞后 | 类型 | 精确表达式 |
|---|---:|---|---|
| CLOSE59 | 59 | 过去收盘/当前收盘 | `Ref($close,59)/$close` |
| CLOSE58 | 58 | 过去收盘/当前收盘 | `Ref($close,58)/$close` |
| CLOSE57 | 57 | 过去收盘/当前收盘 | `Ref($close,57)/$close` |
| CLOSE56 | 56 | 过去收盘/当前收盘 | `Ref($close,56)/$close` |
| CLOSE55 | 55 | 过去收盘/当前收盘 | `Ref($close,55)/$close` |
| CLOSE54 | 54 | 过去收盘/当前收盘 | `Ref($close,54)/$close` |
| CLOSE53 | 53 | 过去收盘/当前收盘 | `Ref($close,53)/$close` |
| CLOSE52 | 52 | 过去收盘/当前收盘 | `Ref($close,52)/$close` |
| CLOSE51 | 51 | 过去收盘/当前收盘 | `Ref($close,51)/$close` |
| CLOSE50 | 50 | 过去收盘/当前收盘 | `Ref($close,50)/$close` |
| CLOSE49 | 49 | 过去收盘/当前收盘 | `Ref($close,49)/$close` |
| CLOSE48 | 48 | 过去收盘/当前收盘 | `Ref($close,48)/$close` |
| CLOSE47 | 47 | 过去收盘/当前收盘 | `Ref($close,47)/$close` |
| CLOSE46 | 46 | 过去收盘/当前收盘 | `Ref($close,46)/$close` |
| CLOSE45 | 45 | 过去收盘/当前收盘 | `Ref($close,45)/$close` |
| CLOSE44 | 44 | 过去收盘/当前收盘 | `Ref($close,44)/$close` |
| CLOSE43 | 43 | 过去收盘/当前收盘 | `Ref($close,43)/$close` |
| CLOSE42 | 42 | 过去收盘/当前收盘 | `Ref($close,42)/$close` |
| CLOSE41 | 41 | 过去收盘/当前收盘 | `Ref($close,41)/$close` |
| CLOSE40 | 40 | 过去收盘/当前收盘 | `Ref($close,40)/$close` |
| CLOSE39 | 39 | 过去收盘/当前收盘 | `Ref($close,39)/$close` |
| CLOSE38 | 38 | 过去收盘/当前收盘 | `Ref($close,38)/$close` |
| CLOSE37 | 37 | 过去收盘/当前收盘 | `Ref($close,37)/$close` |
| CLOSE36 | 36 | 过去收盘/当前收盘 | `Ref($close,36)/$close` |
| CLOSE35 | 35 | 过去收盘/当前收盘 | `Ref($close,35)/$close` |
| CLOSE34 | 34 | 过去收盘/当前收盘 | `Ref($close,34)/$close` |
| CLOSE33 | 33 | 过去收盘/当前收盘 | `Ref($close,33)/$close` |
| CLOSE32 | 32 | 过去收盘/当前收盘 | `Ref($close,32)/$close` |
| CLOSE31 | 31 | 过去收盘/当前收盘 | `Ref($close,31)/$close` |
| CLOSE30 | 30 | 过去收盘/当前收盘 | `Ref($close,30)/$close` |
| CLOSE29 | 29 | 过去收盘/当前收盘 | `Ref($close,29)/$close` |
| CLOSE28 | 28 | 过去收盘/当前收盘 | `Ref($close,28)/$close` |
| CLOSE27 | 27 | 过去收盘/当前收盘 | `Ref($close,27)/$close` |
| CLOSE26 | 26 | 过去收盘/当前收盘 | `Ref($close,26)/$close` |
| CLOSE25 | 25 | 过去收盘/当前收盘 | `Ref($close,25)/$close` |
| CLOSE24 | 24 | 过去收盘/当前收盘 | `Ref($close,24)/$close` |
| CLOSE23 | 23 | 过去收盘/当前收盘 | `Ref($close,23)/$close` |
| CLOSE22 | 22 | 过去收盘/当前收盘 | `Ref($close,22)/$close` |
| CLOSE21 | 21 | 过去收盘/当前收盘 | `Ref($close,21)/$close` |
| CLOSE20 | 20 | 过去收盘/当前收盘 | `Ref($close,20)/$close` |
| CLOSE19 | 19 | 过去收盘/当前收盘 | `Ref($close,19)/$close` |
| CLOSE18 | 18 | 过去收盘/当前收盘 | `Ref($close,18)/$close` |
| CLOSE17 | 17 | 过去收盘/当前收盘 | `Ref($close,17)/$close` |
| CLOSE16 | 16 | 过去收盘/当前收盘 | `Ref($close,16)/$close` |
| CLOSE15 | 15 | 过去收盘/当前收盘 | `Ref($close,15)/$close` |
| CLOSE14 | 14 | 过去收盘/当前收盘 | `Ref($close,14)/$close` |
| CLOSE13 | 13 | 过去收盘/当前收盘 | `Ref($close,13)/$close` |
| CLOSE12 | 12 | 过去收盘/当前收盘 | `Ref($close,12)/$close` |
| CLOSE11 | 11 | 过去收盘/当前收盘 | `Ref($close,11)/$close` |
| CLOSE10 | 10 | 过去收盘/当前收盘 | `Ref($close,10)/$close` |
| CLOSE9 | 9 | 过去收盘/当前收盘 | `Ref($close,9)/$close` |
| CLOSE8 | 8 | 过去收盘/当前收盘 | `Ref($close,8)/$close` |
| CLOSE7 | 7 | 过去收盘/当前收盘 | `Ref($close,7)/$close` |
| CLOSE6 | 6 | 过去收盘/当前收盘 | `Ref($close,6)/$close` |
| CLOSE5 | 5 | 过去收盘/当前收盘 | `Ref($close,5)/$close` |
| CLOSE4 | 4 | 过去收盘/当前收盘 | `Ref($close,4)/$close` |
| CLOSE3 | 3 | 过去收盘/当前收盘 | `Ref($close,3)/$close` |
| CLOSE2 | 2 | 过去收盘/当前收盘 | `Ref($close,2)/$close` |
| CLOSE1 | 1 | 过去收盘/当前收盘 | `Ref($close,1)/$close` |
| CLOSE0 | 0 | 过去收盘/当前收盘 | `$close/$close` |
| OPEN59 | 59 | 过去开盘/当前收盘 | `Ref($open,59)/$close` |
| OPEN58 | 58 | 过去开盘/当前收盘 | `Ref($open,58)/$close` |
| OPEN57 | 57 | 过去开盘/当前收盘 | `Ref($open,57)/$close` |
| OPEN56 | 56 | 过去开盘/当前收盘 | `Ref($open,56)/$close` |
| OPEN55 | 55 | 过去开盘/当前收盘 | `Ref($open,55)/$close` |
| OPEN54 | 54 | 过去开盘/当前收盘 | `Ref($open,54)/$close` |
| OPEN53 | 53 | 过去开盘/当前收盘 | `Ref($open,53)/$close` |
| OPEN52 | 52 | 过去开盘/当前收盘 | `Ref($open,52)/$close` |
| OPEN51 | 51 | 过去开盘/当前收盘 | `Ref($open,51)/$close` |
| OPEN50 | 50 | 过去开盘/当前收盘 | `Ref($open,50)/$close` |
| OPEN49 | 49 | 过去开盘/当前收盘 | `Ref($open,49)/$close` |
| OPEN48 | 48 | 过去开盘/当前收盘 | `Ref($open,48)/$close` |
| OPEN47 | 47 | 过去开盘/当前收盘 | `Ref($open,47)/$close` |
| OPEN46 | 46 | 过去开盘/当前收盘 | `Ref($open,46)/$close` |
| OPEN45 | 45 | 过去开盘/当前收盘 | `Ref($open,45)/$close` |
| OPEN44 | 44 | 过去开盘/当前收盘 | `Ref($open,44)/$close` |
| OPEN43 | 43 | 过去开盘/当前收盘 | `Ref($open,43)/$close` |
| OPEN42 | 42 | 过去开盘/当前收盘 | `Ref($open,42)/$close` |
| OPEN41 | 41 | 过去开盘/当前收盘 | `Ref($open,41)/$close` |
| OPEN40 | 40 | 过去开盘/当前收盘 | `Ref($open,40)/$close` |
| OPEN39 | 39 | 过去开盘/当前收盘 | `Ref($open,39)/$close` |
| OPEN38 | 38 | 过去开盘/当前收盘 | `Ref($open,38)/$close` |
| OPEN37 | 37 | 过去开盘/当前收盘 | `Ref($open,37)/$close` |
| OPEN36 | 36 | 过去开盘/当前收盘 | `Ref($open,36)/$close` |
| OPEN35 | 35 | 过去开盘/当前收盘 | `Ref($open,35)/$close` |
| OPEN34 | 34 | 过去开盘/当前收盘 | `Ref($open,34)/$close` |
| OPEN33 | 33 | 过去开盘/当前收盘 | `Ref($open,33)/$close` |
| OPEN32 | 32 | 过去开盘/当前收盘 | `Ref($open,32)/$close` |
| OPEN31 | 31 | 过去开盘/当前收盘 | `Ref($open,31)/$close` |
| OPEN30 | 30 | 过去开盘/当前收盘 | `Ref($open,30)/$close` |
| OPEN29 | 29 | 过去开盘/当前收盘 | `Ref($open,29)/$close` |
| OPEN28 | 28 | 过去开盘/当前收盘 | `Ref($open,28)/$close` |
| OPEN27 | 27 | 过去开盘/当前收盘 | `Ref($open,27)/$close` |
| OPEN26 | 26 | 过去开盘/当前收盘 | `Ref($open,26)/$close` |
| OPEN25 | 25 | 过去开盘/当前收盘 | `Ref($open,25)/$close` |
| OPEN24 | 24 | 过去开盘/当前收盘 | `Ref($open,24)/$close` |
| OPEN23 | 23 | 过去开盘/当前收盘 | `Ref($open,23)/$close` |
| OPEN22 | 22 | 过去开盘/当前收盘 | `Ref($open,22)/$close` |
| OPEN21 | 21 | 过去开盘/当前收盘 | `Ref($open,21)/$close` |
| OPEN20 | 20 | 过去开盘/当前收盘 | `Ref($open,20)/$close` |
| OPEN19 | 19 | 过去开盘/当前收盘 | `Ref($open,19)/$close` |
| OPEN18 | 18 | 过去开盘/当前收盘 | `Ref($open,18)/$close` |
| OPEN17 | 17 | 过去开盘/当前收盘 | `Ref($open,17)/$close` |
| OPEN16 | 16 | 过去开盘/当前收盘 | `Ref($open,16)/$close` |
| OPEN15 | 15 | 过去开盘/当前收盘 | `Ref($open,15)/$close` |
| OPEN14 | 14 | 过去开盘/当前收盘 | `Ref($open,14)/$close` |
| OPEN13 | 13 | 过去开盘/当前收盘 | `Ref($open,13)/$close` |
| OPEN12 | 12 | 过去开盘/当前收盘 | `Ref($open,12)/$close` |
| OPEN11 | 11 | 过去开盘/当前收盘 | `Ref($open,11)/$close` |
| OPEN10 | 10 | 过去开盘/当前收盘 | `Ref($open,10)/$close` |
| OPEN9 | 9 | 过去开盘/当前收盘 | `Ref($open,9)/$close` |
| OPEN8 | 8 | 过去开盘/当前收盘 | `Ref($open,8)/$close` |
| OPEN7 | 7 | 过去开盘/当前收盘 | `Ref($open,7)/$close` |
| OPEN6 | 6 | 过去开盘/当前收盘 | `Ref($open,6)/$close` |
| OPEN5 | 5 | 过去开盘/当前收盘 | `Ref($open,5)/$close` |
| OPEN4 | 4 | 过去开盘/当前收盘 | `Ref($open,4)/$close` |
| OPEN3 | 3 | 过去开盘/当前收盘 | `Ref($open,3)/$close` |
| OPEN2 | 2 | 过去开盘/当前收盘 | `Ref($open,2)/$close` |
| OPEN1 | 1 | 过去开盘/当前收盘 | `Ref($open,1)/$close` |
| OPEN0 | 0 | 过去开盘/当前收盘 | `$open/$close` |
| HIGH59 | 59 | 过去最高/当前收盘 | `Ref($high,59)/$close` |
| HIGH58 | 58 | 过去最高/当前收盘 | `Ref($high,58)/$close` |
| HIGH57 | 57 | 过去最高/当前收盘 | `Ref($high,57)/$close` |
| HIGH56 | 56 | 过去最高/当前收盘 | `Ref($high,56)/$close` |
| HIGH55 | 55 | 过去最高/当前收盘 | `Ref($high,55)/$close` |
| HIGH54 | 54 | 过去最高/当前收盘 | `Ref($high,54)/$close` |
| HIGH53 | 53 | 过去最高/当前收盘 | `Ref($high,53)/$close` |
| HIGH52 | 52 | 过去最高/当前收盘 | `Ref($high,52)/$close` |
| HIGH51 | 51 | 过去最高/当前收盘 | `Ref($high,51)/$close` |
| HIGH50 | 50 | 过去最高/当前收盘 | `Ref($high,50)/$close` |
| HIGH49 | 49 | 过去最高/当前收盘 | `Ref($high,49)/$close` |
| HIGH48 | 48 | 过去最高/当前收盘 | `Ref($high,48)/$close` |
| HIGH47 | 47 | 过去最高/当前收盘 | `Ref($high,47)/$close` |
| HIGH46 | 46 | 过去最高/当前收盘 | `Ref($high,46)/$close` |
| HIGH45 | 45 | 过去最高/当前收盘 | `Ref($high,45)/$close` |
| HIGH44 | 44 | 过去最高/当前收盘 | `Ref($high,44)/$close` |
| HIGH43 | 43 | 过去最高/当前收盘 | `Ref($high,43)/$close` |
| HIGH42 | 42 | 过去最高/当前收盘 | `Ref($high,42)/$close` |
| HIGH41 | 41 | 过去最高/当前收盘 | `Ref($high,41)/$close` |
| HIGH40 | 40 | 过去最高/当前收盘 | `Ref($high,40)/$close` |
| HIGH39 | 39 | 过去最高/当前收盘 | `Ref($high,39)/$close` |
| HIGH38 | 38 | 过去最高/当前收盘 | `Ref($high,38)/$close` |
| HIGH37 | 37 | 过去最高/当前收盘 | `Ref($high,37)/$close` |
| HIGH36 | 36 | 过去最高/当前收盘 | `Ref($high,36)/$close` |
| HIGH35 | 35 | 过去最高/当前收盘 | `Ref($high,35)/$close` |
| HIGH34 | 34 | 过去最高/当前收盘 | `Ref($high,34)/$close` |
| HIGH33 | 33 | 过去最高/当前收盘 | `Ref($high,33)/$close` |
| HIGH32 | 32 | 过去最高/当前收盘 | `Ref($high,32)/$close` |
| HIGH31 | 31 | 过去最高/当前收盘 | `Ref($high,31)/$close` |
| HIGH30 | 30 | 过去最高/当前收盘 | `Ref($high,30)/$close` |
| HIGH29 | 29 | 过去最高/当前收盘 | `Ref($high,29)/$close` |
| HIGH28 | 28 | 过去最高/当前收盘 | `Ref($high,28)/$close` |
| HIGH27 | 27 | 过去最高/当前收盘 | `Ref($high,27)/$close` |
| HIGH26 | 26 | 过去最高/当前收盘 | `Ref($high,26)/$close` |
| HIGH25 | 25 | 过去最高/当前收盘 | `Ref($high,25)/$close` |
| HIGH24 | 24 | 过去最高/当前收盘 | `Ref($high,24)/$close` |
| HIGH23 | 23 | 过去最高/当前收盘 | `Ref($high,23)/$close` |
| HIGH22 | 22 | 过去最高/当前收盘 | `Ref($high,22)/$close` |
| HIGH21 | 21 | 过去最高/当前收盘 | `Ref($high,21)/$close` |
| HIGH20 | 20 | 过去最高/当前收盘 | `Ref($high,20)/$close` |
| HIGH19 | 19 | 过去最高/当前收盘 | `Ref($high,19)/$close` |
| HIGH18 | 18 | 过去最高/当前收盘 | `Ref($high,18)/$close` |
| HIGH17 | 17 | 过去最高/当前收盘 | `Ref($high,17)/$close` |
| HIGH16 | 16 | 过去最高/当前收盘 | `Ref($high,16)/$close` |
| HIGH15 | 15 | 过去最高/当前收盘 | `Ref($high,15)/$close` |
| HIGH14 | 14 | 过去最高/当前收盘 | `Ref($high,14)/$close` |
| HIGH13 | 13 | 过去最高/当前收盘 | `Ref($high,13)/$close` |
| HIGH12 | 12 | 过去最高/当前收盘 | `Ref($high,12)/$close` |
| HIGH11 | 11 | 过去最高/当前收盘 | `Ref($high,11)/$close` |
| HIGH10 | 10 | 过去最高/当前收盘 | `Ref($high,10)/$close` |
| HIGH9 | 9 | 过去最高/当前收盘 | `Ref($high,9)/$close` |
| HIGH8 | 8 | 过去最高/当前收盘 | `Ref($high,8)/$close` |
| HIGH7 | 7 | 过去最高/当前收盘 | `Ref($high,7)/$close` |
| HIGH6 | 6 | 过去最高/当前收盘 | `Ref($high,6)/$close` |
| HIGH5 | 5 | 过去最高/当前收盘 | `Ref($high,5)/$close` |
| HIGH4 | 4 | 过去最高/当前收盘 | `Ref($high,4)/$close` |
| HIGH3 | 3 | 过去最高/当前收盘 | `Ref($high,3)/$close` |
| HIGH2 | 2 | 过去最高/当前收盘 | `Ref($high,2)/$close` |
| HIGH1 | 1 | 过去最高/当前收盘 | `Ref($high,1)/$close` |
| HIGH0 | 0 | 过去最高/当前收盘 | `$high/$close` |
| LOW59 | 59 | 过去最低/当前收盘 | `Ref($low,59)/$close` |
| LOW58 | 58 | 过去最低/当前收盘 | `Ref($low,58)/$close` |
| LOW57 | 57 | 过去最低/当前收盘 | `Ref($low,57)/$close` |
| LOW56 | 56 | 过去最低/当前收盘 | `Ref($low,56)/$close` |
| LOW55 | 55 | 过去最低/当前收盘 | `Ref($low,55)/$close` |
| LOW54 | 54 | 过去最低/当前收盘 | `Ref($low,54)/$close` |
| LOW53 | 53 | 过去最低/当前收盘 | `Ref($low,53)/$close` |
| LOW52 | 52 | 过去最低/当前收盘 | `Ref($low,52)/$close` |
| LOW51 | 51 | 过去最低/当前收盘 | `Ref($low,51)/$close` |
| LOW50 | 50 | 过去最低/当前收盘 | `Ref($low,50)/$close` |
| LOW49 | 49 | 过去最低/当前收盘 | `Ref($low,49)/$close` |
| LOW48 | 48 | 过去最低/当前收盘 | `Ref($low,48)/$close` |
| LOW47 | 47 | 过去最低/当前收盘 | `Ref($low,47)/$close` |
| LOW46 | 46 | 过去最低/当前收盘 | `Ref($low,46)/$close` |
| LOW45 | 45 | 过去最低/当前收盘 | `Ref($low,45)/$close` |
| LOW44 | 44 | 过去最低/当前收盘 | `Ref($low,44)/$close` |
| LOW43 | 43 | 过去最低/当前收盘 | `Ref($low,43)/$close` |
| LOW42 | 42 | 过去最低/当前收盘 | `Ref($low,42)/$close` |
| LOW41 | 41 | 过去最低/当前收盘 | `Ref($low,41)/$close` |
| LOW40 | 40 | 过去最低/当前收盘 | `Ref($low,40)/$close` |
| LOW39 | 39 | 过去最低/当前收盘 | `Ref($low,39)/$close` |
| LOW38 | 38 | 过去最低/当前收盘 | `Ref($low,38)/$close` |
| LOW37 | 37 | 过去最低/当前收盘 | `Ref($low,37)/$close` |
| LOW36 | 36 | 过去最低/当前收盘 | `Ref($low,36)/$close` |
| LOW35 | 35 | 过去最低/当前收盘 | `Ref($low,35)/$close` |
| LOW34 | 34 | 过去最低/当前收盘 | `Ref($low,34)/$close` |
| LOW33 | 33 | 过去最低/当前收盘 | `Ref($low,33)/$close` |
| LOW32 | 32 | 过去最低/当前收盘 | `Ref($low,32)/$close` |
| LOW31 | 31 | 过去最低/当前收盘 | `Ref($low,31)/$close` |
| LOW30 | 30 | 过去最低/当前收盘 | `Ref($low,30)/$close` |
| LOW29 | 29 | 过去最低/当前收盘 | `Ref($low,29)/$close` |
| LOW28 | 28 | 过去最低/当前收盘 | `Ref($low,28)/$close` |
| LOW27 | 27 | 过去最低/当前收盘 | `Ref($low,27)/$close` |
| LOW26 | 26 | 过去最低/当前收盘 | `Ref($low,26)/$close` |
| LOW25 | 25 | 过去最低/当前收盘 | `Ref($low,25)/$close` |
| LOW24 | 24 | 过去最低/当前收盘 | `Ref($low,24)/$close` |
| LOW23 | 23 | 过去最低/当前收盘 | `Ref($low,23)/$close` |
| LOW22 | 22 | 过去最低/当前收盘 | `Ref($low,22)/$close` |
| LOW21 | 21 | 过去最低/当前收盘 | `Ref($low,21)/$close` |
| LOW20 | 20 | 过去最低/当前收盘 | `Ref($low,20)/$close` |
| LOW19 | 19 | 过去最低/当前收盘 | `Ref($low,19)/$close` |
| LOW18 | 18 | 过去最低/当前收盘 | `Ref($low,18)/$close` |
| LOW17 | 17 | 过去最低/当前收盘 | `Ref($low,17)/$close` |
| LOW16 | 16 | 过去最低/当前收盘 | `Ref($low,16)/$close` |
| LOW15 | 15 | 过去最低/当前收盘 | `Ref($low,15)/$close` |
| LOW14 | 14 | 过去最低/当前收盘 | `Ref($low,14)/$close` |
| LOW13 | 13 | 过去最低/当前收盘 | `Ref($low,13)/$close` |
| LOW12 | 12 | 过去最低/当前收盘 | `Ref($low,12)/$close` |
| LOW11 | 11 | 过去最低/当前收盘 | `Ref($low,11)/$close` |
| LOW10 | 10 | 过去最低/当前收盘 | `Ref($low,10)/$close` |
| LOW9 | 9 | 过去最低/当前收盘 | `Ref($low,9)/$close` |
| LOW8 | 8 | 过去最低/当前收盘 | `Ref($low,8)/$close` |
| LOW7 | 7 | 过去最低/当前收盘 | `Ref($low,7)/$close` |
| LOW6 | 6 | 过去最低/当前收盘 | `Ref($low,6)/$close` |
| LOW5 | 5 | 过去最低/当前收盘 | `Ref($low,5)/$close` |
| LOW4 | 4 | 过去最低/当前收盘 | `Ref($low,4)/$close` |
| LOW3 | 3 | 过去最低/当前收盘 | `Ref($low,3)/$close` |
| LOW2 | 2 | 过去最低/当前收盘 | `Ref($low,2)/$close` |
| LOW1 | 1 | 过去最低/当前收盘 | `Ref($low,1)/$close` |
| LOW0 | 0 | 过去最低/当前收盘 | `$low/$close` |
| VWAP59 | 59 | 过去VWAP/当前收盘 | `Ref($vwap,59)/$close` |
| VWAP58 | 58 | 过去VWAP/当前收盘 | `Ref($vwap,58)/$close` |
| VWAP57 | 57 | 过去VWAP/当前收盘 | `Ref($vwap,57)/$close` |
| VWAP56 | 56 | 过去VWAP/当前收盘 | `Ref($vwap,56)/$close` |
| VWAP55 | 55 | 过去VWAP/当前收盘 | `Ref($vwap,55)/$close` |
| VWAP54 | 54 | 过去VWAP/当前收盘 | `Ref($vwap,54)/$close` |
| VWAP53 | 53 | 过去VWAP/当前收盘 | `Ref($vwap,53)/$close` |
| VWAP52 | 52 | 过去VWAP/当前收盘 | `Ref($vwap,52)/$close` |
| VWAP51 | 51 | 过去VWAP/当前收盘 | `Ref($vwap,51)/$close` |
| VWAP50 | 50 | 过去VWAP/当前收盘 | `Ref($vwap,50)/$close` |
| VWAP49 | 49 | 过去VWAP/当前收盘 | `Ref($vwap,49)/$close` |
| VWAP48 | 48 | 过去VWAP/当前收盘 | `Ref($vwap,48)/$close` |
| VWAP47 | 47 | 过去VWAP/当前收盘 | `Ref($vwap,47)/$close` |
| VWAP46 | 46 | 过去VWAP/当前收盘 | `Ref($vwap,46)/$close` |
| VWAP45 | 45 | 过去VWAP/当前收盘 | `Ref($vwap,45)/$close` |
| VWAP44 | 44 | 过去VWAP/当前收盘 | `Ref($vwap,44)/$close` |
| VWAP43 | 43 | 过去VWAP/当前收盘 | `Ref($vwap,43)/$close` |
| VWAP42 | 42 | 过去VWAP/当前收盘 | `Ref($vwap,42)/$close` |
| VWAP41 | 41 | 过去VWAP/当前收盘 | `Ref($vwap,41)/$close` |
| VWAP40 | 40 | 过去VWAP/当前收盘 | `Ref($vwap,40)/$close` |
| VWAP39 | 39 | 过去VWAP/当前收盘 | `Ref($vwap,39)/$close` |
| VWAP38 | 38 | 过去VWAP/当前收盘 | `Ref($vwap,38)/$close` |
| VWAP37 | 37 | 过去VWAP/当前收盘 | `Ref($vwap,37)/$close` |
| VWAP36 | 36 | 过去VWAP/当前收盘 | `Ref($vwap,36)/$close` |
| VWAP35 | 35 | 过去VWAP/当前收盘 | `Ref($vwap,35)/$close` |
| VWAP34 | 34 | 过去VWAP/当前收盘 | `Ref($vwap,34)/$close` |
| VWAP33 | 33 | 过去VWAP/当前收盘 | `Ref($vwap,33)/$close` |
| VWAP32 | 32 | 过去VWAP/当前收盘 | `Ref($vwap,32)/$close` |
| VWAP31 | 31 | 过去VWAP/当前收盘 | `Ref($vwap,31)/$close` |
| VWAP30 | 30 | 过去VWAP/当前收盘 | `Ref($vwap,30)/$close` |
| VWAP29 | 29 | 过去VWAP/当前收盘 | `Ref($vwap,29)/$close` |
| VWAP28 | 28 | 过去VWAP/当前收盘 | `Ref($vwap,28)/$close` |
| VWAP27 | 27 | 过去VWAP/当前收盘 | `Ref($vwap,27)/$close` |
| VWAP26 | 26 | 过去VWAP/当前收盘 | `Ref($vwap,26)/$close` |
| VWAP25 | 25 | 过去VWAP/当前收盘 | `Ref($vwap,25)/$close` |
| VWAP24 | 24 | 过去VWAP/当前收盘 | `Ref($vwap,24)/$close` |
| VWAP23 | 23 | 过去VWAP/当前收盘 | `Ref($vwap,23)/$close` |
| VWAP22 | 22 | 过去VWAP/当前收盘 | `Ref($vwap,22)/$close` |
| VWAP21 | 21 | 过去VWAP/当前收盘 | `Ref($vwap,21)/$close` |
| VWAP20 | 20 | 过去VWAP/当前收盘 | `Ref($vwap,20)/$close` |
| VWAP19 | 19 | 过去VWAP/当前收盘 | `Ref($vwap,19)/$close` |
| VWAP18 | 18 | 过去VWAP/当前收盘 | `Ref($vwap,18)/$close` |
| VWAP17 | 17 | 过去VWAP/当前收盘 | `Ref($vwap,17)/$close` |
| VWAP16 | 16 | 过去VWAP/当前收盘 | `Ref($vwap,16)/$close` |
| VWAP15 | 15 | 过去VWAP/当前收盘 | `Ref($vwap,15)/$close` |
| VWAP14 | 14 | 过去VWAP/当前收盘 | `Ref($vwap,14)/$close` |
| VWAP13 | 13 | 过去VWAP/当前收盘 | `Ref($vwap,13)/$close` |
| VWAP12 | 12 | 过去VWAP/当前收盘 | `Ref($vwap,12)/$close` |
| VWAP11 | 11 | 过去VWAP/当前收盘 | `Ref($vwap,11)/$close` |
| VWAP10 | 10 | 过去VWAP/当前收盘 | `Ref($vwap,10)/$close` |
| VWAP9 | 9 | 过去VWAP/当前收盘 | `Ref($vwap,9)/$close` |
| VWAP8 | 8 | 过去VWAP/当前收盘 | `Ref($vwap,8)/$close` |
| VWAP7 | 7 | 过去VWAP/当前收盘 | `Ref($vwap,7)/$close` |
| VWAP6 | 6 | 过去VWAP/当前收盘 | `Ref($vwap,6)/$close` |
| VWAP5 | 5 | 过去VWAP/当前收盘 | `Ref($vwap,5)/$close` |
| VWAP4 | 4 | 过去VWAP/当前收盘 | `Ref($vwap,4)/$close` |
| VWAP3 | 3 | 过去VWAP/当前收盘 | `Ref($vwap,3)/$close` |
| VWAP2 | 2 | 过去VWAP/当前收盘 | `Ref($vwap,2)/$close` |
| VWAP1 | 1 | 过去VWAP/当前收盘 | `Ref($vwap,1)/$close` |
| VWAP0 | 0 | 过去VWAP/当前收盘 | `$vwap/$close` |
| VOLUME59 | 59 | 过去成交量/当前成交量 | `Ref($volume,59)/($volume+1e-12)` |
| VOLUME58 | 58 | 过去成交量/当前成交量 | `Ref($volume,58)/($volume+1e-12)` |
| VOLUME57 | 57 | 过去成交量/当前成交量 | `Ref($volume,57)/($volume+1e-12)` |
| VOLUME56 | 56 | 过去成交量/当前成交量 | `Ref($volume,56)/($volume+1e-12)` |
| VOLUME55 | 55 | 过去成交量/当前成交量 | `Ref($volume,55)/($volume+1e-12)` |
| VOLUME54 | 54 | 过去成交量/当前成交量 | `Ref($volume,54)/($volume+1e-12)` |
| VOLUME53 | 53 | 过去成交量/当前成交量 | `Ref($volume,53)/($volume+1e-12)` |
| VOLUME52 | 52 | 过去成交量/当前成交量 | `Ref($volume,52)/($volume+1e-12)` |
| VOLUME51 | 51 | 过去成交量/当前成交量 | `Ref($volume,51)/($volume+1e-12)` |
| VOLUME50 | 50 | 过去成交量/当前成交量 | `Ref($volume,50)/($volume+1e-12)` |
| VOLUME49 | 49 | 过去成交量/当前成交量 | `Ref($volume,49)/($volume+1e-12)` |
| VOLUME48 | 48 | 过去成交量/当前成交量 | `Ref($volume,48)/($volume+1e-12)` |
| VOLUME47 | 47 | 过去成交量/当前成交量 | `Ref($volume,47)/($volume+1e-12)` |
| VOLUME46 | 46 | 过去成交量/当前成交量 | `Ref($volume,46)/($volume+1e-12)` |
| VOLUME45 | 45 | 过去成交量/当前成交量 | `Ref($volume,45)/($volume+1e-12)` |
| VOLUME44 | 44 | 过去成交量/当前成交量 | `Ref($volume,44)/($volume+1e-12)` |
| VOLUME43 | 43 | 过去成交量/当前成交量 | `Ref($volume,43)/($volume+1e-12)` |
| VOLUME42 | 42 | 过去成交量/当前成交量 | `Ref($volume,42)/($volume+1e-12)` |
| VOLUME41 | 41 | 过去成交量/当前成交量 | `Ref($volume,41)/($volume+1e-12)` |
| VOLUME40 | 40 | 过去成交量/当前成交量 | `Ref($volume,40)/($volume+1e-12)` |
| VOLUME39 | 39 | 过去成交量/当前成交量 | `Ref($volume,39)/($volume+1e-12)` |
| VOLUME38 | 38 | 过去成交量/当前成交量 | `Ref($volume,38)/($volume+1e-12)` |
| VOLUME37 | 37 | 过去成交量/当前成交量 | `Ref($volume,37)/($volume+1e-12)` |
| VOLUME36 | 36 | 过去成交量/当前成交量 | `Ref($volume,36)/($volume+1e-12)` |
| VOLUME35 | 35 | 过去成交量/当前成交量 | `Ref($volume,35)/($volume+1e-12)` |
| VOLUME34 | 34 | 过去成交量/当前成交量 | `Ref($volume,34)/($volume+1e-12)` |
| VOLUME33 | 33 | 过去成交量/当前成交量 | `Ref($volume,33)/($volume+1e-12)` |
| VOLUME32 | 32 | 过去成交量/当前成交量 | `Ref($volume,32)/($volume+1e-12)` |
| VOLUME31 | 31 | 过去成交量/当前成交量 | `Ref($volume,31)/($volume+1e-12)` |
| VOLUME30 | 30 | 过去成交量/当前成交量 | `Ref($volume,30)/($volume+1e-12)` |
| VOLUME29 | 29 | 过去成交量/当前成交量 | `Ref($volume,29)/($volume+1e-12)` |
| VOLUME28 | 28 | 过去成交量/当前成交量 | `Ref($volume,28)/($volume+1e-12)` |
| VOLUME27 | 27 | 过去成交量/当前成交量 | `Ref($volume,27)/($volume+1e-12)` |
| VOLUME26 | 26 | 过去成交量/当前成交量 | `Ref($volume,26)/($volume+1e-12)` |
| VOLUME25 | 25 | 过去成交量/当前成交量 | `Ref($volume,25)/($volume+1e-12)` |
| VOLUME24 | 24 | 过去成交量/当前成交量 | `Ref($volume,24)/($volume+1e-12)` |
| VOLUME23 | 23 | 过去成交量/当前成交量 | `Ref($volume,23)/($volume+1e-12)` |
| VOLUME22 | 22 | 过去成交量/当前成交量 | `Ref($volume,22)/($volume+1e-12)` |
| VOLUME21 | 21 | 过去成交量/当前成交量 | `Ref($volume,21)/($volume+1e-12)` |
| VOLUME20 | 20 | 过去成交量/当前成交量 | `Ref($volume,20)/($volume+1e-12)` |
| VOLUME19 | 19 | 过去成交量/当前成交量 | `Ref($volume,19)/($volume+1e-12)` |
| VOLUME18 | 18 | 过去成交量/当前成交量 | `Ref($volume,18)/($volume+1e-12)` |
| VOLUME17 | 17 | 过去成交量/当前成交量 | `Ref($volume,17)/($volume+1e-12)` |
| VOLUME16 | 16 | 过去成交量/当前成交量 | `Ref($volume,16)/($volume+1e-12)` |
| VOLUME15 | 15 | 过去成交量/当前成交量 | `Ref($volume,15)/($volume+1e-12)` |
| VOLUME14 | 14 | 过去成交量/当前成交量 | `Ref($volume,14)/($volume+1e-12)` |
| VOLUME13 | 13 | 过去成交量/当前成交量 | `Ref($volume,13)/($volume+1e-12)` |
| VOLUME12 | 12 | 过去成交量/当前成交量 | `Ref($volume,12)/($volume+1e-12)` |
| VOLUME11 | 11 | 过去成交量/当前成交量 | `Ref($volume,11)/($volume+1e-12)` |
| VOLUME10 | 10 | 过去成交量/当前成交量 | `Ref($volume,10)/($volume+1e-12)` |
| VOLUME9 | 9 | 过去成交量/当前成交量 | `Ref($volume,9)/($volume+1e-12)` |
| VOLUME8 | 8 | 过去成交量/当前成交量 | `Ref($volume,8)/($volume+1e-12)` |
| VOLUME7 | 7 | 过去成交量/当前成交量 | `Ref($volume,7)/($volume+1e-12)` |
| VOLUME6 | 6 | 过去成交量/当前成交量 | `Ref($volume,6)/($volume+1e-12)` |
| VOLUME5 | 5 | 过去成交量/当前成交量 | `Ref($volume,5)/($volume+1e-12)` |
| VOLUME4 | 4 | 过去成交量/当前成交量 | `Ref($volume,4)/($volume+1e-12)` |
| VOLUME3 | 3 | 过去成交量/当前成交量 | `Ref($volume,3)/($volume+1e-12)` |
| VOLUME2 | 2 | 过去成交量/当前成交量 | `Ref($volume,2)/($volume+1e-12)` |
| VOLUME1 | 1 | 过去成交量/当前成交量 | `Ref($volume,1)/($volume+1e-12)` |
| VOLUME0 | 0 | 过去成交量/当前成交量 | `$volume/($volume+1e-12)` |

## 9. 生产实现与失效监控

1. 保持输入形状`[样本, 时间, 通道]`或明确的扁平顺序；训练和实盘不得改变列序。
2. 复权必须在生成全部60日序列前完成，避免除权日形成假路径。
3. 对停牌日不要简单前向填充后当作真实交易；同时提供可交易掩码、距离上次交易天数。
4. 监控每个序列块的PSI、缺失率和极端值；VOLUME块特别监控当前量分母。
5. 训练标签若为未来2日收益，应purge重叠样本；时序模型随机打散前要先按日期分割。
6. 深度模型的“因子重要性”不是单列稳定经济含义；应使用遮挡、分滞后带消融和跨时间稳定性验证。

## 来源

- [Q1] Microsoft Qlib `Alpha360DL.get_feature_config`: https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py
- Qlib Dataset Zoo: https://github.com/microsoft/qlib#quant-dataset-zoo
