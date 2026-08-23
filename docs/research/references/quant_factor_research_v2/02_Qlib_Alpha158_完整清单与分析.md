
---
title: Qlib Alpha158完整清单与逐族分析
updated: 2026-08-14
source: Microsoft Qlib loader.py
feature_count: 158
---

# Qlib Alpha158：完整清单、逻辑、适用性与失效条件

## 1. 结构与定位

Qlib官方实现的默认Alpha158由：

- 9个当日K线形态；
- 4个当日价格/VWAP相对收盘归一化特征；
- 29个滚动特征族 × 5个窗口（5、10、20、30、60日）；

合计`9 + 4 + 29×5 = 158`。官方代码位于`qlib/contrib/data/loader.py`。[Q1]

Alpha158不是158条独立经济假设，而是一个**人工工程化的日频量价特征面板**。其优势是对线性模型、树模型和较小样本较友好；缺点是窗口高度相关、存在代数冗余，而且许多特征方向必须由模型或样本外检验决定。

## 2. 窗口解释

| 窗口 | 近似持有/信息尺度 | 更适合 | 风险 |
|---:|---|---|---|
| 5 | 一周以内 | 高换手、事件、短反转、活跃中小盘 | 噪声、成本、涨跌停 |
| 10 | 两周 | 短趋势和反转折中 | 参数敏感 |
| 20 | 约一月 | 月度选股、行为和流动性 | 风格切换 |
| 30 | 约一个半月 | 更平滑的趋势/波动 | 反应滞后 |
| 60 | 一季度 | 大中盘、趋势与风险状态 | 次新缺失、制度断点、滞后 |

同一特征的5个窗口不应默认全部保留。应看相关聚类、增量IC和模型选择稳定性。

## 3. 13个非滚动特征

| 特征 | 精确表达式 | 类型 | 逻辑/方向 |
|---|---|---|---|
| KMID | `($close-$open)/$open` | K线实体相对开盘 | 日内方向/动量；高值表示收盘强于开盘 |
| KLEN | `($high-$low)/$open` | 日内振幅相对开盘 | 波动与分歧；高值通常意味着更高短期风险 |
| KMID2 | `($close-$open)/($high-$low+1e-12)` | 实体占振幅比例 | 收盘方向在全天区间中的强度 |
| KUP | `($high-Greater($open,$close))/$open` | 上影线相对开盘 | 上方抛压/冲高回落 |
| KUP2 | `($high-Greater($open,$close))/($high-$low+1e-12)` | 上影线占振幅 | 去价格尺度的上方抛压 |
| KLOW | `(Less($open,$close)-$low)/$open` | 下影线相对开盘 | 下方承接/探底回升 |
| KLOW2 | `(Less($open,$close)-$low)/($high-$low+1e-12)` | 下影线占振幅 | 去价格尺度的下方承接 |
| KSFT | `(2*$close-$high-$low)/$open` | 收盘相对日内中点 | 收盘靠近高/低位的方向性 |
| KSFT2 | `(2*$close-$high-$low)/($high-$low+1e-12)` | 收盘中点偏移占振幅 | 标准化收盘位置 |
| OPEN0 | `$open/$close` | 当日开盘/收盘 | 日内收益的反向比率 |
| HIGH0 | `$high/$close` | 当日最高/收盘 | 收盘距高点 |
| LOW0 | `$low/$close` | 当日最低/收盘 | 收盘距低点 |
| VWAP0 | `$vwap/$close` | 当日VWAP/收盘 | 成交重心与收盘偏离 |

## 4. 29个滚动特征族

## ROC：价格反转/动量位置

**核心逻辑。** 高值表示当前价格低于d日前，按原值更接近“过去跌幅”；可由模型学习反转或趋势。

**更适合。** 短窗适合活跃/高波股票；长窗适合趋势稳定的大中盘。

**主要失效。** 结构性跳空、强单边趋势、复权错误。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| ROC5 | 5 | `Ref($close,5)/$close` |
| ROC10 | 10 | `Ref($close,10)/$close` |
| ROC20 | 20 | `Ref($close,20)/$close` |
| ROC30 | 30 | `Ref($close,30)/$close` |
| ROC60 | 60 | `Ref($close,60)/$close` |
## MA：均线偏离

**核心逻辑。** 高值表示当前收盘低于过去均价，典型均值回归或趋势位置特征。

**更适合。** 震荡和回撤修复；长窗对成熟股票更稳。

**主要失效。** 永久重估、强趋势、长停牌。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| MA5 | 5 | `Mean($close,5)/$close` |
| MA10 | 10 | `Mean($close,10)/$close` |
| MA20 | 20 | `Mean($close,20)/$close` |
| MA30 | 30 | `Mean($close,30)/$close` |
| MA60 | 60 | `Mean($close,60)/$close` |
## STD：价格波动率

**核心逻辑。** 归一化价格水平波动，兼具总风险和高波偏好/惩罚。

**更适合。** 波动横截面差异大；低风险/反转模型。

**主要失效。** 事件波动持续、价格水平变化导致比例失真。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| STD5 | 5 | `Std($close,5)/$close` |
| STD10 | 10 | `Std($close,10)/$close` |
| STD20 | 20 | `Std($close,20)/$close` |
| STD30 | 30 | `Std($close,30)/$close` |
| STD60 | 60 | `Std($close,60)/$close` |
## BETA：线性趋势斜率

**核心逻辑。** 对过去价格做时间回归的斜率；方向和速度。这里的`BETA`是时间趋势斜率，不是股票相对市场指数的CAPM Beta。

**更适合。** 持续趋势，流动性较好的股票。

**主要失效。** V形反转、跳空、非线性路径。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| BETA5 | 5 | `Slope($close,5)/$close` |
| BETA10 | 10 | `Slope($close,10)/$close` |
| BETA20 | 20 | `Slope($close,20)/$close` |
| BETA30 | 30 | `Slope($close,30)/$close` |
| BETA60 | 60 | `Slope($close,60)/$close` |
## RSQR：趋势拟合质量

**核心逻辑。** 衡量线性趋势解释度；不提供方向，适合作为BETA/动量的置信度。

**更适合。** 路径平滑、趋势持久的大中盘。

**主要失效。** 震荡、事件跳变；单独使用无方向。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| RSQR5 | 5 | `Rsquare($close,5)` |
| RSQR10 | 10 | `Rsquare($close,10)` |
| RSQR20 | 20 | `Rsquare($close,20)` |
| RSQR30 | 30 | `Rsquare($close,30)` |
| RSQR60 | 60 | `Rsquare($close,60)` |
## RESI：趋势残差

**核心逻辑。** 当前价格相对线性趋势的残差，常用于趋势内超调/回归。

**更适合。** 趋势背景稳定且存在短期偏离。

**主要失效。** 趋势模型错误、结构断点。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| RESI5 | 5 | `Resi($close,5)/$close` |
| RESI10 | 10 | `Resi($close,10)/$close` |
| RESI20 | 20 | `Resi($close,20)/$close` |
| RESI30 | 30 | `Resi($close,30)/$close` |
| RESI60 | 60 | `Resi($close,60)/$close` |
## MAX：距近期高点

**核心逻辑。** 高值表示当前收盘远低于近期最高价；回撤/峰值距离。

**更适合。** 回撤修复、反转；长历史股票。

**主要失效。** 持续下跌或真突破后价格锚改变。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| MAX5 | 5 | `Max($high,5)/$close` |
| MAX10 | 10 | `Max($high,10)/$close` |
| MAX20 | 20 | `Max($high,20)/$close` |
| MAX30 | 30 | `Max($high,30)/$close` |
| MAX60 | 60 | `Max($high,60)/$close` |
## MIN：距近期低点

**核心逻辑。** 低值/高值反映当前收盘相对近期低点的位置。

**更适合。** 区间交易和突破判断。

**主要失效。** 价格限制、异常低价。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| MIN5 | 5 | `Min($low,5)/$close` |
| MIN10 | 10 | `Min($low,10)/$close` |
| MIN20 | 20 | `Min($low,20)/$close` |
| MIN30 | 30 | `Min($low,30)/$close` |
| MIN60 | 60 | `Min($low,60)/$close` |
## QTLU：上分位价格位置

**核心逻辑。** 当前价格相对过去80%分位的偏离，较MAX稳健。

**更适合。** 异常值较多但区间位置稳定。

**主要失效。** 结构性趋势改变。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| QTLU5 | 5 | `Quantile($close,5,0.8)/$close` |
| QTLU10 | 10 | `Quantile($close,10,0.8)/$close` |
| QTLU20 | 20 | `Quantile($close,20,0.8)/$close` |
| QTLU30 | 30 | `Quantile($close,30,0.8)/$close` |
| QTLU60 | 60 | `Quantile($close,60,0.8)/$close` |
## QTLD：下分位价格位置

**核心逻辑。** 当前价格相对过去20%分位的偏离，较MIN稳健。

**更适合。** 震荡和超卖修复。

**主要失效。** 持续基本面恶化。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| QTLD5 | 5 | `Quantile($close,5,0.2)/$close` |
| QTLD10 | 10 | `Quantile($close,10,0.2)/$close` |
| QTLD20 | 20 | `Quantile($close,20,0.2)/$close` |
| QTLD30 | 30 | `Quantile($close,30,0.2)/$close` |
| QTLD60 | 60 | `Quantile($close,60,0.2)/$close` |
## RANK：收盘时序排名

**核心逻辑。** 当前收盘在自身d日历史中的相对位置。

**更适合。** 趋势/反转均可由模型学习；跨价格尺度稳健。

**主要失效。** 窗口太短造成并列，涨跌停。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| RANK5 | 5 | `Rank($close,5)` |
| RANK10 | 10 | `Rank($close,10)` |
| RANK20 | 20 | `Rank($close,20)` |
| RANK30 | 30 | `Rank($close,30)` |
| RANK60 | 60 | `Rank($close,60)` |
## RSV：随机指标位置

**核心逻辑。** 收盘在d日高低区间的位置。

**更适合。** 震荡、超买超卖、价量确认模型。

**主要失效。** 区间宽度近零、真突破。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| RSV5 | 5 | `($close-Min($low,5))/(Max($high,5)-Min($low,5)+1e-12)` |
| RSV10 | 10 | `($close-Min($low,10))/(Max($high,10)-Min($low,10)+1e-12)` |
| RSV20 | 20 | `($close-Min($low,20))/(Max($high,20)-Min($low,20)+1e-12)` |
| RSV30 | 30 | `($close-Min($low,30))/(Max($high,30)-Min($low,30)+1e-12)` |
| RSV60 | 60 | `($close-Min($low,60))/(Max($high,60)-Min($low,60)+1e-12)` |
## IMAX：高点出现时点

**核心逻辑。** 近期最高点距当前的新旧程度。

**更适合。** 峰值后衰减、反转/趋势门控。

**主要失效。** 多个并列高点、窗口边界跳变。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| IMAX5 | 5 | `IdxMax($high,5)/5` |
| IMAX10 | 10 | `IdxMax($high,10)/10` |
| IMAX20 | 20 | `IdxMax($high,20)/20` |
| IMAX30 | 30 | `IdxMax($high,30)/30` |
| IMAX60 | 60 | `IdxMax($high,60)/60` |
## IMIN：低点出现时点

**核心逻辑。** 近期最低点距当前的新旧程度。

**更适合。** 低点修复、趋势门控。

**主要失效。** 并列低点、异常成交。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| IMIN5 | 5 | `IdxMin($low,5)/5` |
| IMIN10 | 10 | `IdxMin($low,10)/10` |
| IMIN20 | 20 | `IdxMin($low,20)/20` |
| IMIN30 | 30 | `IdxMin($low,30)/30` |
| IMIN60 | 60 | `IdxMin($low,60)/60` |
## IMXD：高低点时序差

**核心逻辑。** 区分先低后高或先高后低的路径方向。

**更适合。** 路径依赖动量/反转。

**主要失效。** 极值时点不稳定、跳空。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| IMXD5 | 5 | `(IdxMax($high,5)-IdxMin($low,5))/5` |
| IMXD10 | 10 | `(IdxMax($high,10)-IdxMin($low,10))/10` |
| IMXD20 | 20 | `(IdxMax($high,20)-IdxMin($low,20))/20` |
| IMXD30 | 30 | `(IdxMax($high,30)-IdxMin($low,30))/30` |
| IMXD60 | 60 | `(IdxMax($high,60)-IdxMin($low,60))/60` |
## CORR：价格—成交量相关

**核心逻辑。** 价格水平与对数成交量同步程度；可能代表确认或拥挤。

**更适合。** 成交活跃、中小盘行为信息较多。

**主要失效。** 被动调仓、大宗交易、单边行情。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| CORR5 | 5 | `Corr($close,Log($volume+1),5)` |
| CORR10 | 10 | `Corr($close,Log($volume+1),10)` |
| CORR20 | 20 | `Corr($close,Log($volume+1),20)` |
| CORR30 | 30 | `Corr($close,Log($volume+1),30)` |
| CORR60 | 60 | `Corr($close,Log($volume+1),60)` |
## CORD：收益—量变相关

**核心逻辑。** 价格收益与成交量变化的同步/背离。

**更适合。** 信息扩散和短期价量结构。

**主要失效。** 零成交、比值异常、极短窗噪声。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| CORD5 | 5 | `Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),5)` |
| CORD10 | 10 | `Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),10)` |
| CORD20 | 20 | `Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),20)` |
| CORD30 | 30 | `Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),30)` |
| CORD60 | 60 | `Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),60)` |
## CNTP：上涨日比例

**核心逻辑。** 过去d日上涨频率；不考虑幅度。

**更适合。** 方向持续性、低噪声趋势。

**主要失效。** 最小价位噪声、频繁平盘。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| CNTP5 | 5 | `Mean($close>Ref($close,1),5)` |
| CNTP10 | 10 | `Mean($close>Ref($close,1),10)` |
| CNTP20 | 20 | `Mean($close>Ref($close,1),20)` |
| CNTP30 | 30 | `Mean($close>Ref($close,1),30)` |
| CNTP60 | 60 | `Mean($close>Ref($close,1),60)` |
## CNTN：下跌日比例

**核心逻辑。** 过去d日下跌频率。

**更适合。** 趋势与反转状态。

**主要失效。** 平盘占比高、停牌。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| CNTN5 | 5 | `Mean($close<Ref($close,1),5)` |
| CNTN10 | 10 | `Mean($close<Ref($close,1),10)` |
| CNTN20 | 20 | `Mean($close<Ref($close,1),20)` |
| CNTN30 | 30 | `Mean($close<Ref($close,1),30)` |
| CNTN60 | 60 | `Mean($close<Ref($close,1),60)` |
## CNTD：上涨减下跌频率

**核心逻辑。** 方向广度；与CNTP/CNTN存在确定性关系。

**更适合。** 趋势状态识别。

**主要失效。** 作为独立特征时冗余。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| CNTD5 | 5 | `Mean($close>Ref($close,1),5)-Mean($close<Ref($close,1),5)` |
| CNTD10 | 10 | `Mean($close>Ref($close,1),10)-Mean($close<Ref($close,1),10)` |
| CNTD20 | 20 | `Mean($close>Ref($close,1),20)-Mean($close<Ref($close,1),20)` |
| CNTD30 | 30 | `Mean($close>Ref($close,1),30)-Mean($close<Ref($close,1),30)` |
| CNTD60 | 60 | `Mean($close>Ref($close,1),60)-Mean($close<Ref($close,1),60)` |
## SUMP：正收益幅度占比

**核心逻辑。** 类似RSI的正向价格变化份额。

**更适合。** 趋势和超买超卖。

**主要失效。** 窗口内无波动、结构性跳空。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| SUMP5 | 5 | `Sum(Greater($close-Ref($close,1),0),5)/(Sum(Abs($close-Ref($close,1)),5)+1e-12)` |
| SUMP10 | 10 | `Sum(Greater($close-Ref($close,1),0),10)/(Sum(Abs($close-Ref($close,1)),10)+1e-12)` |
| SUMP20 | 20 | `Sum(Greater($close-Ref($close,1),0),20)/(Sum(Abs($close-Ref($close,1)),20)+1e-12)` |
| SUMP30 | 30 | `Sum(Greater($close-Ref($close,1),0),30)/(Sum(Abs($close-Ref($close,1)),30)+1e-12)` |
| SUMP60 | 60 | `Sum(Greater($close-Ref($close,1),0),60)/(Sum(Abs($close-Ref($close,1)),60)+1e-12)` |
## SUMN：负收益幅度占比

**核心逻辑。** 负向价格变化份额，与SUMP近似互补。

**更适合。** 下行压力与修复。

**主要失效。** 与SUMP高度冗余。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| SUMN5 | 5 | `Sum(Greater(Ref($close,1)-$close,0),5)/(Sum(Abs($close-Ref($close,1)),5)+1e-12)` |
| SUMN10 | 10 | `Sum(Greater(Ref($close,1)-$close,0),10)/(Sum(Abs($close-Ref($close,1)),10)+1e-12)` |
| SUMN20 | 20 | `Sum(Greater(Ref($close,1)-$close,0),20)/(Sum(Abs($close-Ref($close,1)),20)+1e-12)` |
| SUMN30 | 30 | `Sum(Greater(Ref($close,1)-$close,0),30)/(Sum(Abs($close-Ref($close,1)),30)+1e-12)` |
| SUMN60 | 60 | `Sum(Greater(Ref($close,1)-$close,0),60)/(Sum(Abs($close-Ref($close,1)),60)+1e-12)` |
## SUMD：正负幅度差

**核心逻辑。** 等于SUMP-SUMN，属于确定性派生。

**更适合。** 方向强度。

**主要失效。** 与SUMP/SUMN共线。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| SUMD5 | 5 | `(Sum(Greater($close-Ref($close,1),0),5)-Sum(Greater(Ref($close,1)-$close,0),5))/(Sum(Abs($close-Ref($close,1)),5)+1e-12)` |
| SUMD10 | 10 | `(Sum(Greater($close-Ref($close,1),0),10)-Sum(Greater(Ref($close,1)-$close,0),10))/(Sum(Abs($close-Ref($close,1)),10)+1e-12)` |
| SUMD20 | 20 | `(Sum(Greater($close-Ref($close,1),0),20)-Sum(Greater(Ref($close,1)-$close,0),20))/(Sum(Abs($close-Ref($close,1)),20)+1e-12)` |
| SUMD30 | 30 | `(Sum(Greater($close-Ref($close,1),0),30)-Sum(Greater(Ref($close,1)-$close,0),30))/(Sum(Abs($close-Ref($close,1)),30)+1e-12)` |
| SUMD60 | 60 | `(Sum(Greater($close-Ref($close,1),0),60)-Sum(Greater(Ref($close,1)-$close,0),60))/(Sum(Abs($close-Ref($close,1)),60)+1e-12)` |
## VMA：成交量均值/当前量

**核心逻辑。** 高值表示当前量低于历史均量；反向成交量冲击。

**更适合。** 异常量、注意力和均值回归。

**主要失效。** 停牌、零成交、复权量口径。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| VMA5 | 5 | `Mean($volume,5)/($volume+1e-12)` |
| VMA10 | 10 | `Mean($volume,10)/($volume+1e-12)` |
| VMA20 | 20 | `Mean($volume,20)/($volume+1e-12)` |
| VMA30 | 30 | `Mean($volume,30)/($volume+1e-12)` |
| VMA60 | 60 | `Mean($volume,60)/($volume+1e-12)` |
## VSTD：成交量波动/当前量

**核心逻辑。** 量能不稳定性相对当前量。

**更适合。** 活跃度状态、微观结构。

**主要失效。** 当前量接近零导致爆炸。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| VSTD5 | 5 | `Std($volume,5)/($volume+1e-12)` |
| VSTD10 | 10 | `Std($volume,10)/($volume+1e-12)` |
| VSTD20 | 20 | `Std($volume,20)/($volume+1e-12)` |
| VSTD30 | 30 | `Std($volume,30)/($volume+1e-12)` |
| VSTD60 | 60 | `Std($volume,60)/($volume+1e-12)` |
## WVMA：量加权绝对收益变异系数

**核心逻辑。** 衡量“价格冲击×成交量”的不稳定性。

**更适合。** 高频/短期风险和异常交易。

**主要失效。** 极端日主导、均值近零。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| WVMA5 | 5 | `Std(Abs($close/Ref($close,1)-1)*$volume,5)/(Mean(Abs($close/Ref($close,1)-1)*$volume,5)+1e-12)` |
| WVMA10 | 10 | `Std(Abs($close/Ref($close,1)-1)*$volume,10)/(Mean(Abs($close/Ref($close,1)-1)*$volume,10)+1e-12)` |
| WVMA20 | 20 | `Std(Abs($close/Ref($close,1)-1)*$volume,20)/(Mean(Abs($close/Ref($close,1)-1)*$volume,20)+1e-12)` |
| WVMA30 | 30 | `Std(Abs($close/Ref($close,1)-1)*$volume,30)/(Mean(Abs($close/Ref($close,1)-1)*$volume,30)+1e-12)` |
| WVMA60 | 60 | `Std(Abs($close/Ref($close,1)-1)*$volume,60)/(Mean(Abs($close/Ref($close,1)-1)*$volume,60)+1e-12)` |
## VSUMP：正向量变占比

**核心逻辑。** 成交量上升幅度占总量变的份额。

**更适合。** 注意力上升、量能趋势。

**主要失效。** 复权量和停牌处理错误。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| VSUMP5 | 5 | `Sum(Greater($volume-Ref($volume,1),0),5)/(Sum(Abs($volume-Ref($volume,1)),5)+1e-12)` |
| VSUMP10 | 10 | `Sum(Greater($volume-Ref($volume,1),0),10)/(Sum(Abs($volume-Ref($volume,1)),10)+1e-12)` |
| VSUMP20 | 20 | `Sum(Greater($volume-Ref($volume,1),0),20)/(Sum(Abs($volume-Ref($volume,1)),20)+1e-12)` |
| VSUMP30 | 30 | `Sum(Greater($volume-Ref($volume,1),0),30)/(Sum(Abs($volume-Ref($volume,1)),30)+1e-12)` |
| VSUMP60 | 60 | `Sum(Greater($volume-Ref($volume,1),0),60)/(Sum(Abs($volume-Ref($volume,1)),60)+1e-12)` |
## VSUMN：负向量变占比

**核心逻辑。** 成交量下降幅度份额，与VSUMP近似互补。

**更适合。** 缩量状态。

**主要失效。** 与VSUMP高度冗余。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| VSUMN5 | 5 | `Sum(Greater(Ref($volume,1)-$volume,0),5)/(Sum(Abs($volume-Ref($volume,1)),5)+1e-12)` |
| VSUMN10 | 10 | `Sum(Greater(Ref($volume,1)-$volume,0),10)/(Sum(Abs($volume-Ref($volume,1)),10)+1e-12)` |
| VSUMN20 | 20 | `Sum(Greater(Ref($volume,1)-$volume,0),20)/(Sum(Abs($volume-Ref($volume,1)),20)+1e-12)` |
| VSUMN30 | 30 | `Sum(Greater(Ref($volume,1)-$volume,0),30)/(Sum(Abs($volume-Ref($volume,1)),30)+1e-12)` |
| VSUMN60 | 60 | `Sum(Greater(Ref($volume,1)-$volume,0),60)/(Sum(Abs($volume-Ref($volume,1)),60)+1e-12)` |
## VSUMD：正负量变差

**核心逻辑。** 等于VSUMP-VSUMN，确定性派生。

**更适合。** 量能方向强度。

**主要失效。** 共线与零分母。

| 特征 | 窗口 | 精确表达式 |
|---|---:|---|
| VSUMD5 | 5 | `(Sum(Greater($volume-Ref($volume,1),0),5)-Sum(Greater(Ref($volume,1)-$volume,0),5))/(Sum(Abs($volume-Ref($volume,1)),5)+1e-12)` |
| VSUMD10 | 10 | `(Sum(Greater($volume-Ref($volume,1),0),10)-Sum(Greater(Ref($volume,1)-$volume,0),10))/(Sum(Abs($volume-Ref($volume,1)),10)+1e-12)` |
| VSUMD20 | 20 | `(Sum(Greater($volume-Ref($volume,1),0),20)-Sum(Greater(Ref($volume,1)-$volume,0),20))/(Sum(Abs($volume-Ref($volume,1)),20)+1e-12)` |
| VSUMD30 | 30 | `(Sum(Greater($volume-Ref($volume,1),0),30)-Sum(Greater(Ref($volume,1)-$volume,0),30))/(Sum(Abs($volume-Ref($volume,1)),30)+1e-12)` |
| VSUMD60 | 60 | `(Sum(Greater($volume-Ref($volume,1),0),60)-Sum(Greater(Ref($volume,1)-$volume,0),60))/(Sum(Abs($volume-Ref($volume,1)),60)+1e-12)` |

## 5. 内部冗余

### 5.1 确定性关系

对每个窗口d：

- `CNTD_d = CNTP_d - CNTN_d`；
- `SUMD_d = SUMP_d - SUMN_d`；
- `VSUMD_d = VSUMP_d - VSUMN_d`。

因此至少有15个特征是同族内确定性派生。在线性模型中同时放入三者会造成共线；树模型也可能重复分裂。

### 5.2 近似互补

- `SUMP + SUMN ≈ 1`；
- `VSUMP + VSUMN ≈ 1`；
- 无平盘时`CNTP + CNTN = 1`。

epsilon、平盘和零变化使它们不总是严格等式，但排序信息高度重复。

### 5.3 K线代数关系

忽略epsilon时：

- `KMID ≈ KMID2 × KLEN`；
- `KUP ≈ KUP2 × KLEN`；
- `KLOW ≈ KLOW2 × KLEN`；
- `KSFT ≈ KSFT2 × KLEN`。

这些关系不意味着必须全部删除：非线性模型可能从显式比例中受益；但应归入同一冗余簇。

## 6. 股票适用性

- **大盘高流动性**：30/60日趋势、RSQR、BETA、波动、行业中性后的价量关系更稳定；短窗毛IC较弱但可实现性好。
- **中盘活跃**：5/10/20日价量、反转、RSV、CORR/CORD通常更有行为信息，是Alpha158较自然的主战场。
- **小盘高波动**：短窗和量能信号可能更强，但必须加入成交额门槛、涨跌停可交易掩码和冲击成本；否则容易得到“不可成交Alpha”。
- **次新股**：60日特征缺失；建议上市满120–250交易日再进入完整模型，或单建短历史模型。
- **周期股**：纯量价可以捕捉趋势，但在商品/政策驱动的永久重估阶段，反转类特征易失效。

## 7. 生产实现建议

1. 使用Qlib原式作为黄金测试集，随机抽取股票/日期逐项对比。
2. 明确`Rank`在Qlib表达式中的时序语义；不要与Alpha101的横截面`rank`混淆。
3. 价格和VWAP按同一复权因子处理；成交量是否反向复权必须与数据源一致。
4. 任何除以当前成交量的特征都要记录零/极小量比例；停牌日不应简单填0后参与滚动。
5. 对窗口组进行组内正交、PCA、聚类选代表或正则化，不要把158维等同于158个独立信息源。
6. 标签需明确，如`Ref(close,-2)/Ref(close,-1)-1`对应何时形成信号和何时成交；避免Qlib配置与自建回测的标签错位。

## 来源

- [Q1] Microsoft Qlib `Alpha158DL.get_feature_config`: https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py
- Qlib仓库及Dataset Zoo: https://github.com/microsoft/qlib
