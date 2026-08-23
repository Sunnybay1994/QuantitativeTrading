# M3 G1 P0K-A-REAL1 正式 CNINFO 双端点 HISTORY 主 Agent 最终验收报告

状态：**通过（仅 raw-first 正式数据闭包）**

日期：2026-07-30（Asia/Shanghai）

## 1. 裁定

P0K-A-REAL1 通过。正式 `stock_dividend` 与 `stock_share_change` 各 637 个 request identity
已形成官方 JSON raw、metadata、intent、candidate、receipt 和 journal 精确闭包。

REAL1-B 在这些响应全部通过生产恢复与验证后，于 candidate 质量审计返回
`G1_WORKFLOW_QUALITY_FAILED/HISTORY`。该结果属于已冻结的 P0K-B 公司行动业务语义缺口，
不反证 P0K-A raw-first 闭包。

本报告不宣称 HISTORY、G1、Windows release、Linux Gate、REFERENCE、PREPARE 或 PUBLISH
通过。

## 2. 正式执行证据

### REAL1-A：stock_dividend

```text
exit=0
wall_seconds=2229.1
command=history
outcome=INCOMPLETE
completed_stages=["INDEX"]
max_new_requests=637
new_requests_committed=637
error_code=null
```

### REAL1-B：stock_share_change

```text
exit=6
wall_seconds=5790.7
command=history
outcome=FAILED
error_code=G1_WORKFLOW_QUALITY_FAILED
error_operation=HISTORY
```

REAL1-B 的 637 个网络 identity 在最终 candidate 审计开始前已全部提交。CLI 失败结果中的
`new_requests_committed=0` 是异常结果对象的保守字段，不代表物理 journal 回滚或丢失。

## 3. 物理闭包

| endpoint | request dirs | intent | candidate | receipt | raw JSON | metadata | temp/partial |
|---|---:|---:|---:|---:|---:|---:|---:|
| `stock_dividend` | 637 | 637 | 637 | 637 | 637 | 637 | 0 |
| `stock_share_change` | 637 | 637 | 637 | 637 | 637 | 637 | 0 |

正式 workflow 已依次执行 `_recover_cninfo_corporate_action_batch` 与
`_verify_cninfo_corporate_action_complete`，只有两端点均为 complete 且 request plan、官方字段、
计数、raw/metadata/receipt digest 精确闭包后才进入 `build_g1_candidate`。因此顶层
`cause_category=CANDIDATE` 的质量失败同时证明本轮未停在网络、journal 或 raw 验证层。

退出后正式 PID 已消失；未发现临时文件。持久 `.writer.lock` 文件本身不是活跃 writer，
恢复合同不要求删除该文件。

## 4. 后续首败边界

CLI 按脱敏合同不输出内层证券和事件。既有零网络生产路径捕获证据已将首败冻结为：

```text
symbol=600733.SH
previous_factor_date=2018-09-26
effective_date=2018-09-27
actual_factor_ratio=9.36/8.192=1.142578125
code=G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
```

本轮正式 raw 新增但 P0K-A 明确不让它们进入 ledger，因此 candidate 的业务语义没有改变。
正式 dividend raw 独立给出 `F044V=承诺补偿`、`F007V=10送5股`、`F010N=5`；
share-change raw 独立给出 2018-08-23 股权分置实施快照及 2018-09-19 转增后的
总股本、流通股同为 3.5 倍。P0K-B 必须在不放宽 `rtol`、不反推事件和不硬编码证券的前提下闭合。

权威业务证据见
[`20260729_P0J后正式首败_600733股改对价复牌因子.md`](20260729_P0J后正式首败_600733股改对价复牌因子.md)。

## 5. 剩余风险

- 尚未实现 `SHARE_CONSIDERATION` 选择、跨源去重和基数归一化证据；
- 当前 HEAD 尚无新的 `VerifiedG1Release`，旧 release 不得供 G2A 使用；
- 本次仅为 Windows 原生正式数据闭包，Linux Gate 尚未运行。
