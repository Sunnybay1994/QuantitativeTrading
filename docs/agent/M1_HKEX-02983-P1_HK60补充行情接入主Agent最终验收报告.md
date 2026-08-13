# M1-HKEX-02983-P1：HK60 补充行情接入主 Agent 最终验收报告

日期：2026-08-08  
结论：**PASS（P1 工程合同）**

## 验收结论

接受 P1 对正式 HK history v2 finalize 的最小扩展：只有 v2 plan 的 unresolved 精确为
`02983.HK@2026-07-10` 时，入口才从显式 retained raw bytes fresh 调用已验收的 HKEX Daily Quotations
verifier。补充行保持 `source=hkex`、股数 volume、完整 HKD sales turnover 和 `adj_factor=1.0`；可发布 key
闭包使用 `effective_expected_dates`，不会让已有权威 no-trade evidence 的 key 回流。

`hk-history-finalize-v2` receipt 绑定 HKEX evidence/raw/source-record 与补充 frame 内容摘要；三文件
no-clobber、重复执行字节幂等，raw、plan、receipt 或 clean 漂移均 fail closed。CLI 仅在 finalize 模式读取
显式 raw 文件，其他模式在读取前拒绝并保持稳定脱敏错误码。

独立初验增加的“伪造 effective expected 让 no-trade key 回流”反例在任何写入前返回
`HK_HISTORY_PLAN_CONFLICT`。主验另核对 canonical v2 receipt 的 tuple/list wire 比较修复没有放宽原始字节
和 identity 闭包。

## 主验结果

- Windows Miniforge：`28 passed, 1 skipped`；Ruff PASS；mypy 两个生产文件 PASS。
- WSL Miniforge base、`/mnt/f` DrvFS：`29 passed`；Ruff PASS；mypy 两个生产文件 PASS。
- `git diff --check` 留待 M1 合流审计统一执行；本包未 git add/commit。

## 未关闭边界

本 PASS 只关闭 02983 补充路径的工程合同。2026-05-05 HKEX 历史 Daily Quotations 当前官方直链在搜索
索引中仍可定位，但本轮 CLI 与浏览器实测返回已迁移/404/503，未取得可留存 raw，因此
`01065.HK@2026-05-05` 权威无交易 evidence 仍未成立。正式 v2 recover/finalize、双 Route HK60、WSL/ext4
发布 Gate 与 M1 整体 Gate 保持未通过。

