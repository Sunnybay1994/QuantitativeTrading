# M1 HK-CA-P1B：HK 总回报研究价格 Development 发布实现交付报告

日期：2026-08-09  
状态：实现与自测完成；待独立初验和主 Agent 最终验收  
性质：development 工程合同证据；不是正式 HK60/M1/ext4 Gate

## 1. 完成内容

- 在 `ResearchPrice1dSchema.adjustment_method` 现有 SSOT 中加入
  `HK_GROSS_TOTAL_RETURN_V1`，未增加平行枚举或扩展五列契约。
- 新增 `quant.data.hk_total_return_research_price` 的两个窄公共入口与 exact-final、process-local
  development publication capability。
- 每次 publish/verify 均先调用 P1A fresh verifier，再 clone schedule 与未复权 bar；调用者仍承担任务单冻结的
  quiescence 边界。
- 按 Decimal50 / HALF_EVEN 递推 close-only gross total return；输出仅在末端量化 12 位。现金加拆股同日按
  `M * close + C`，冻结手算为 194，不是 196。
- 在任何 group 降维前拒绝“不同 ex-date 映射到同一恢复 bar”和“同日多个 share-changing leg”；允许多笔
  HKD 股息加至多一个 BONUS/SPLIT。
- 发布路径固定为 caller-created `development/hk_gross_total_return_v1/<artifact_id>/`，四文件 exact，逐文件
  exclusive-create/no-clobber；完整同身份目录 fresh verify 后幂等复用。
- artifact identity 绑定固定政策、aware UTC `as_of`、完整 P1A/P0/implementation/bar 身份以及量化后 12 位
  逻辑行 hash；parquet bytes SHA/size 只进入 manifest/receipt，不进入跨平台逻辑身份。
- verifier fresh 重建价格、request、manifest、receipt，校验 parquet schema/域/顺序/行内容、四文件集合、
  canonical JSON、物理 hash/size 与 publication root 身份连续性。
- 普通失败 rollback 仅删除本调用 exclusive-created 且 inode/size/content 仍匹配的文件；竞争替换内容保留。
- 所有 public 失败在离开 active exception 后重建为稳定、脱敏错误，hostile 递归异常图不泄露路径、TOKEN 或
  source payload。

## 2. 修改文件

- `src/quant/domain/schemas.py`
- `src/quant/data/hk_total_return_research_price.py`（新增）
- `tests/unit/test_schemas.py`
- `tests/unit/test_hk_total_return_research_price.py`（新增）
- 本任务单状态行
- 本交付报告

未修改 P0/PRE/PRE-B/P1A 实现、storage/connectors/backtest、M3/M4、正式数据、journal 或正式发布根；未
联网、未 add/commit。

## 3. 验证证据

### Windows 原生 Miniforge

- 定向 Ruff：通过。
- 定向 mypy：`Success: no issues found in 2 source files`。
- P1B + schema 定向：`77 passed, 1 skipped`；skip 是 Windows 当前权限不允许创建目录 symlink，WSL 对应
  用例实际执行通过。
- P1B + P1A fresh 合同：`30 passed, 1 skipped`。
- 最终格式化后 P1B + schema 定向复跑：`23 passed, 1 skipped`；新增文件 `ruff format --check` 通过。
- development root 身份连续性补强后的 P1B 最终复跑：`22 passed, 1 skipped`，Ruff/mypy 通过。
- Windows junction/reparse 实际创建并拒绝后的最终复跑：`23 passed, 1 skipped`；仅目录 symlink 因主机权限
  skip，junction 用例实际通过。
- cold import：公开表面 exact，导入通过。

### WSL Miniforge base

- 同范围 Ruff：通过。
- 同范围 mypy：`Success: no issues found in 2 source files`。
- P1B + P1A fresh + schema 合同：`33 passed`，无 skip。
- 最终格式化后 P1B + schema 定向复跑：`24 passed`，无 skip。
- development root 身份连续性补强后的 P1B 最终复跑：`23 passed`，无 skip，Ruff/mypy 通过。
- 跨平台最终复跑：`23 passed, 1 skipped`；仅 Windows junction 专用用例按平台跳过，Linux symlink 用例
  实际通过。
- cold import：通过。
- `findmnt -T .`：`drvfs /mnt/f`，因此这里只证明 WSL/DrvFS 开发兼容，不是 ext4 Gate。

固定 fixture 在 Windows 与 WSL 均断言：

```text
artifact_id = 7e287fd010c41f53f1f62d2c3cdb07a8cbaee9a72d2921177465242fe09d1ae6
00005.HK@2026-05-08 = 194.000000000000
00005.HK@2026-05-09 = 222.291666666667
```

覆盖 exact capability、pickle/subclass、真实 P1A fresh rebuild、首值锚定、无行动、BONUS、SPLIT、多股息、
194 非 196、不同 ex-date 碰撞、多 share leg、prewindow/future identity、非正/NaN/Inf/overflow、四文件逐一
漂移、extra/missing 结构、same-identity replay、copied root、symlink、whole-resign、root 中途替换、竞争 rollback
身份以及 hostile 递归异常图。

## 4. 准确边界与剩余风险

本轮只能表述为“HK gross-total-return development contract 与 development receipt 实现自测通过”。它不处理
RIGHTS、CNY FX、税费、withholding、账户 entitlement、adjusted OHLCV 或成交模拟，也不声称断电原子、formal
immutable publish 或 ext4 等价。正式 02983 metadata、licensed 01065 issue/spec、formal V3 migration、真实
HK action source、HK60、M1 与 ext4 Gate 继续开放。
