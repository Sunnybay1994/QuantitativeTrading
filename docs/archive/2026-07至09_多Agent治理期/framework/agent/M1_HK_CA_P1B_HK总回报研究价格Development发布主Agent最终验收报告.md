# M1 HK-CA-P1B：HK 总回报研究价格 Development 发布主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅 development contract/receipt）**

## 1. 验收结论

P1B 已从 fresh P1A application plan与verified未复权HK bars生成close-only gross total-return研究价格；支持
HKD DIVIDEND、BONUS、SPLIT，固定公式 `adjusted_prev * (M*close+C)/previous_close`，Decimal50内部递推、
HALF_EVEN输出12位，并发布不可混淆的development四文件闭包。

同日现金加split手算为 `2*96+2=194`，不是196；多个cash可求和，但不同ex-date压到同一恢复bar或多个
share-changing leg均fail closed。RIGHTS/CNY FX/税费/账户entitlement继续不在v1范围。

## 2. 发布与身份核对

- method exact `HK_GROSS_TOTAL_RETURN_V1`，source exact `derived_hk_bar_and_ca_v1`；不复用A股mapper。
- classification/gate claim exact为development；不生成或冒充`VerifiedG1Release`，不写clean/formal HK60/journal。
- request/parquet/manifest/receipt exact四文件、no-clobber、fresh replay、identity-aware rollback与root continuity成立。
- Windows与WSL固定fixture逻辑artifact id一致：
  `7e287fd010c41f53f1f62d2c3cdb07a8cbaee9a72d2921177465242fe09d1ae6`。

## 3. 验证

- 实现者：Windows `23 passed, 1 skipped`，WSL base `23 passed, 1 skipped`；两平台Ruff/mypy/cold-import通过。
- 独立初验：两平台各 `89 passed, 1 skipped`；whole-resign、合法新closure、194、多cash+唯一share、
  ex-date碰撞与hostile IO通过。
- 主 Agent：focused `23 passed, 1 skipped in 3.43s`；Ruff PASS；mypy三生产文件PASS。
- 定向diff检查无错误。

## 4. 诚实边界

exact-bytes copied-root/ABA在development威胁模型内允许；本包不声称崩溃原子或formal immutable publish。
当前WSL为DrvFS，不是ext4。

正式P1C materializer/loader仍必须等待正式HK60 v3 bar closure与真实licensed HK公司行动provenance，不能把本
development产物改标签、复制或重签成formal。02983可信metadata、licensed01065 issue/spec、HK60、M1与ext4
Gate均继续开放；在真实来源到齐前暂停新增M1 fixture代码。
