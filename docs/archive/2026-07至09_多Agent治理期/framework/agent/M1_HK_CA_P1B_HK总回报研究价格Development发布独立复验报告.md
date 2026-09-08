# M1 HK-CA-P1B：HK 总回报研究价格 Development 发布独立复验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**PASS（仅 development 工程合同）**

## 1. 结论与范围

P1B 实现与冻结任务单一致：它 fresh-verify P1A application plan，按
`(M * raw_close + C) / previous_raw_close` 计算 close-only gross total return，以 Decimal50 / HALF_EVEN
完成递推并仅在输出端量化 12 位，再发布身份明确的四文件 development 产物。公开结果没有冒充
`VerifiedG1Release`，也没有写正式 HK60、journal、clean store 或正式发布根。

本报告只证明 **HK gross-total-return development contract 与 development receipt 通过独立初验**。
02983 retained metadata、licensed 01065 issue/spec、真实 HK corporate-action source、formal V3 migration、
HK60、M1 及 ext4 Gate 均未由本包关闭。

## 2. 静态合同复核

- `ResearchPrice1dSchema` 只在现有 `adjustment_method` SSOT 中增加
  `HK_GROSS_TOTAL_RETURN_V1`；输出仍为 exact 五列，source 固定为
  `derived_hk_bar_and_ca_v1`。
- publish 与 verify 均先调用 P1A public fresh verifier；之后克隆 schedule 与未复权 bars。实现没有以
  mtime、重复 sweep 或假锁扩大任务单冻结的 caller-quiescence 信任边界。
- 首 retained bar 以 raw close 锚定；后续同一 application bar 允许多笔 HKD DIVIDEND 求和及至多一个
  BONUS/SPLIT。现金与 share leg 同时按 `M * close + C` 生效。
- 分组前检查同一 application bar 的 ex-date 唯一性及 share-changing leg 唯一性；不同 ex-date 因停牌
  压到同一恢复 bar、或多个 share leg，均 fail closed。
- `BASELINE_PREWINDOW` 与 `OUTSIDE_FUTURE_WINDOW` 不进入数值，但完整 P1A schedule identity 仍进入
  artifact identity。
- request、parquet、manifest、receipt 互相绑定；verifier fresh 重建逻辑行、元数据、所有 JSON 与
  parquet schema/domain/order/content。物理 parquet SHA/size 不进入跨平台逻辑 artifact id。
- development root、namespace、artifact root 和普通文件均检查 plain-directory/file 身份；写入使用
  exclusive-create/no-clobber，普通 rollback 仅删除仍匹配本调用 identity、size、content 的对象。
- 禁止依赖扫描未发现 M3 private publisher、A 股 ResearchPrice pipeline、clean store、connector、socket、
  requests、墙钟、`data/legacy` 或 `VerifiedG1Release`。

## 3. 独立对抗性复验

除实现者测试外，另在临时目录执行未落盘探针：

1. **194 非 196**：previous close 100、application close 96、2:1 split、gross cash 2，输出为
   `194.000000000000`；后续递推为 `222.291666666667`。
2. **多现金 + 唯一 share**：两笔 dividend 加一个 split 被接受；不同 ex-date 压到同一 application bar
   返回 `HK_TOTAL_RETURN_GROUP_UNSUPPORTED`。
3. **合法另一 upstream closure**：修改完整上游 schedule closure 后可发布并 fresh verify，新 artifact id
   与旧 id 不同；旧 publication 不可用新 closure 验证。
4. **整包 whole-resign 攻击**：将 request/manifest/receipt 的 `gate_claim` 改成 `formal`，并重算公开
   request/manifest hash 链，仍因 fresh rebuild 与固定元数据不符而返回
   `HK_TOTAL_RETURN_PUBLICATION_INVALID`。
5. **hostile I/O 异常图**：写入层抛出带路径、TOKEN、raw payload 且 self-cause 的递归异常，public error
   稳定为 `HK_TOTAL_RETURN_IO_FAILED`，cause/context 均为 `None`，traceback 不泄露 payload。
6. **root replacement / copy / replay**：持续替换 publication root 被既有测试拒绝；合法复制根与相同
   artifact replay 会重新 fresh verify。精确字节复制根在验证中发生 ABA 后恢复原目录可被接受；这是任务单
   明确允许 copied root、且明确不声明 formal immutable publish/断电原子的 development 边界。任何内容漂移、
   mixed closure 或最终目录身份漂移仍会被重建比较拒绝，因此本观察不作为 P1B development 阻断项。
7. **数值与跨平台身份**：0、负值、NaN、Inf、超大 Decimal 指数均拒绝；Windows 与 WSL base 对固定
   fixture 均断言同一 artifact id `7e287fd010c41f53f1f62d2c3cdb07a8cbaee9a72d2921177465242fe09d1ae6`
   及相同行内容，覆盖 Decimal50/12dp 逻辑身份。

实现者矩阵同时覆盖 capability exact-final、pickle/subclass、real P1A fresh rebuild、BONUS/SPLIT、普通
停牌恢复、prewindow/future identity、四文件逐一漂移、extra/missing、symlink/junction、partial replay、
竞争 rollback 及 public surface exact。

## 4. 独立验证证据

### Windows 原生 Miniforge

- P1B + P1A + schemas 定向 pytest：`89 passed, 1 skipped`；skip 为当前主机不允许目录 symlink，Windows
  junction 专用拒绝用例实际执行。
- 定向 Ruff：`All checks passed!`
- 定向 mypy：`Success: no issues found in 2 source files`
- P1B 新增文件 format check：`2 files already formatted`
- cold import 与 exact `__all__`：通过。

首次 pytest 收集因根仓库 editable install 抢占隔离工作树源码而失败；显式将该工作树 `src` 置于
`PYTHONPATH` 并禁用 pytest cache 后，上述 89/1 结果通过。该首次失败属于测试环境选择，不是产品失败。

### WSL Miniforge base

- 同范围定向 pytest：`89 passed, 1 skipped`；skip 为 Windows junction 专用用例，Linux symlink 拒绝用例
  实际执行。
- 定向 Ruff：`All checks passed!`
- 定向 mypy：`Success: no issues found in 2 source files`
- P1B 新增文件 format check：`2 files already formatted`
- cold import 与 exact public surface：通过。
- `findmnt -T ...`：`drvfs F:\\ /mnt/f`。因此这里只证明 WSL/DrvFS development 兼容性，不是 ext4 Gate。

## 5. 工作树与独立性

独立初验未修改生产代码或实现者测试，未联网、未 add/commit；唯一新增文件为本报告。工作树原有大量
P0/PRE/PRE-B/P1A 与 HK history 脏文件、未跟踪报告及 pytest 目录均原样保留。P1B 白名单内实际变更为
schema method、P1B 新模块/测试及任务/交付文档；共享 `schemas.py` 中其余既有 HK 变更不归本包单独认领。

## 6. 剩余风险

- 本发布器没有宣称断电原子、formal immutable publish 或 ext4 等价；exact-copy ABA 观察属于这一明确边界。
- RIGHTS、CNY FX、税费/withholding、账户 entitlement、可交易股数、adjusted OHLCV 与成交模拟仍不在 P1B。
- 正式 M1 仍依赖可信 02983 retained metadata、licensed 01065 issue/spec/finality、正式迁移与真实 source/Gate
  证据。

因此独立初验结论为：**PASS，可进入主 Agent 最终验收；只可表述为 development contract/receipt 通过。**
