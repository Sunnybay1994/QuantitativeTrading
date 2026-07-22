# M3 HISTORY-BATCH100 真实恢复执行任务单

日期：2026-07-18  
冻结角色：主 Agent  
状态：**已获用户持续 API 授权，按本任务书有界执行**

## 1. 前置事实

- PILOT10 与 BATCH25 已连续真实成功并经生产 verifier 闭合。
- 当前 baseline：`history_total=3186`、`verified_reusable=149`、`missing=3037`、计划内 partial=0、`completed_stages=[INDEX]`。
- 用户授权后续 Tushare API 由主 Agent 按 2000 积分权限及端点限频自行统筹，不再逐批请求批准。
- 仍使用 WSL Miniforge `base`、单一 writer、冻结配置 `request_rate_per_minute=60`、`max_attempts=5`。

## 2. 批次身份与预算

按生产 HISTORY canonical request-id 顺序选择当前前 100 个 missing identity：

```text
identity set sha256 = 92e172109d01fee347a34f9c54a618286294e6a771ca85510813c676a2d5869f
first id = 0eeb666a5181d6117b7568c77500792f8dedd8b981b1271948118ad0a9d536d1
last id  = 1826e2b70ec6a8347ac7b28a1683578709609eb2007a6453a0504a1bb52ffacb

adj_factor = 18
daily      = 11
dividend   = 29
stk_limit  = 28
suspend_d  = 14
```

唯一网络命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 100
```

预算：最多 100 个新 committed identity；每 identity 最多 5 attempts，故合同上限 500 attempts。已有 149 个 verified receipt 不计入新额度。

## 3. 停止与失败语义

- 命令只运行一次；任何权限、rate-limit 重试耗尽、网络、非允许空响应、row-limit、contract、journal/raw/receipt 错误立即停止，不补跑余额。
- 不提高 request rate，不并发第二个 HISTORY writer，不用 sleep 绕端点限频，不修改 endpoint policy。
- 不调用已知无权限的 ETF/HK factor 等端点，不启动 REFERENCE/PREPARE/PUBLISH/run-all。
- 实际 attempt 数若无独立证据，只报告单命令、committed 数和 500 上限。

## 4. 成功验收

全成功预期：

```text
new_requests_committed = 100
verified_reusable = 249
missing = 2937
planned partial = 0
completed_stages = [INDEX]
outcome = INCOMPLETE
```

执行后必须：

1. 运行生产 `status`；
2. 对全部现有 HISTORY receipt 调用 `verify_tushare_receipt`；
3. 验证 spec/request/raw identity、endpoint policy、bytes/metadata/content digest；
4. 核对计数守恒、endpoint 增量、计划内 partial 与旧 INDEX/月窗目录闭包；
5. 形成主 Agent 执行与验证报告。

## 5. 流程边界

用户 24 小时临时简化期间不调用外部 Agent；由主 Agent直接执行和验证，不生成虚假的外部独立初验结论。只允许正常新增 raw/journal/receipt 与对应报告，不修改生产代码、测试、配置或路线图。
