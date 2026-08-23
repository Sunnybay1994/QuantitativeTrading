# M3 G1 B2A 请求计划与 Journal 返工交付报告

日期：2026-07-13  
原任务书：[`M3_G1_B2A请求计划与Journal实现初验任务单.md`](M3_G1_B2A请求计划与Journal实现初验任务单.md)  
原实现报告：[`M3_G1_B2A请求计划与Journal交付报告.md`](M3_G1_B2A请求计划与Journal交付报告.md)  
独立初验：[`M3_G1_B2A请求计划与Journal独立初验报告.md`](M3_G1_B2A请求计划与Journal独立初验报告.md)  
状态：4 个 P1 已返工并完成实现 Agent 自测；等待独立复验，不代表 B2A、B2、G1 或 M3 通过

## 1. 返工边界

本轮严格限制在：

- `src/quant/data/m3_backfill.py`；
- `src/quant/data/storage.py`；
- `tests/unit/test_m3_backfill_requests.py`；
- `tests/unit/test_storage.py`；
- 本返工报告。

未修改独立初验报告、SSOT、路线图或 Gate；未读取 `_old/`、Tushare 本地 token 配置，未联网或调用
真实供应商接口。

独立初验 A01–A12 的等价反例先转为生产测试。修复前定向结果为 **69 通过、12 失败**；12 个失败均落在
四个 P1 的目标分支。A13–A18 原有行为保持通过。修复后又把 A15–A17 的连续退避、classifier 敏感
异常和真实 weekday session 反例固化为生产回归。

## 2. P1-1：direct-caller 信任边界未闭合

### 现象

- 非规范 `daily` spec 可以直接装入 `TushareRequestBatch`；
- 空 `HISTORY` batch 可以冒充最终 history 阶段并组成 plan；
- plan 信任嵌套 batch 自报 hash；
- `VerifiedRawResponse` 只检查 64 hex 形状和 frame 行列，伪造 receipt hash 或改 frame 内容仍可构造。

### 初次为何漏掉

初次实现把“executor 在 IO 前重验”误当成了所有入口的统一信任边界。生产测试也只把非规范 spec 送到
executor，未直接测试 `Batch/Plan/Verified` 构造。结果是执行路径安全，但这些以“已批次化/已验证”命名
的公共对象仍能由 direct caller 伪造并流入后续模块。

### 根因与应如何思考

领域对象的名字和类型本身就是信任声明。`Batch` 必须证明其每个子 spec 合法，`Plan` 必须证明两个子 batch
仍合法，`Verified` 必须证明 receipt bytes 身份和 frame 内容，而不能只检查自报字段的外形。外层对象必须
递归重建并验证嵌套对象，不能假设 frozen dataclass 从未被旁路修改。

### 修改

- batch `__post_init__` 重建每个 spec，并执行 endpoint 参数键、固定 fields、日期、代码契约；
- `INDEX_WEIGHT` 与最终 `HISTORY` batch 均不得为空，phase endpoint 闭包仍严格验证；
- plan `__post_init__` 重建并重验两个 batch，再重算跨 batch 唯一性和 plan hash；
- `VerifiedRawResponse` 重建 spec/receipt，比较完整 request 语义，按 writer 的 canonical `asdict` bytes
  机械重算 `receipt_sha256`，并重算 frame 逻辑 content digest；
- `verify_tushare_receipt` 对非 canonical receipt bytes 返回稳定 `RECEIPT_CANONICAL_BYTES_MISMATCH`。

### 生产反例与通过条件

- 非规范 endpoint 参数直接构造 batch 失败；
- 空 HISTORY batch 失败；
- 篡改已构造嵌套 batch 后再构造 plan 失败；
- `receipt_sha256="0"*64` 失败；相同行列但改一个 frame 值也失败；
- 正常 planner 和严格 receipt reader 保持通过。

## 3. P1-2：raw/journal root 预检太晚且祖先检查不完整

### 现象

raw root 自身为 symlink 时先调用 connector，父级 symlink 则会被完全忽略；journal parent symlink 也能把
证据写到外部目标。root 被普通文件占用时同样可能到联网后才失败。

### 初次为何漏掉

初次实现只在 executor 开头检查 `journal_root.is_symlink()`，raw 检查留给网络返回后的 `RawStore`。
`_reject_symlinks` 又从 root 向下检查，不检查 root 的既存祖先。测试只覆盖了最终 data path 的 symlink，
没有验证“任何副作用之前”的两个 root 联合预检。

### 根因与应如何思考

路径安全不只是“最终文件仍能打开”。在网络、clock、sleep、mkdir、lock、intent 任一副作用前，必须先证明
两个控制根的整条既存祖先链都是实际目录且没有 symlink。写入层仍要二次检查，以缩小 preflight 与 write
之间的替换窗口。

### 修改

- executor 在任何 mkdir/lock/intent/API/clock/sleep 前，对 raw/journal root 使用 `lstat` 检查自身和全部
  既存祖先；symlink、非目录和检查 IO 异常都返回稳定脱敏错误；
- journal root 创建后、request dir 创建后再次检查，避免只依赖一次 preflight；
- descendant containment 同时检查 lexical relative、resolved containment、各级 symlink 和非目录祖先；
- `RawStore.write_request/verify_request` 保留独立的 root 祖先和 descendant 二次检查；
- root 文件替换、路径检查 OSError/resolve 错误均转换为稳定错误且 `from None`。

### 生产反例与通过条件

覆盖 raw root symlink、raw parent symlink、journal parent symlink、raw root 普通文件，以及直接调用
`RawStore` 的 root/parent symlink。全部满足：

- connector 调用 0；
- fake monotonic/sleep 调用 0；
- journal 和 symlink 指向的真实目录无新证据；
- message、repr、`format_exception` 不含测试临时物理路径。

## 4. P1-3：journal 白名单只查看普通文件

### 现象

`_validate_journal_files` 使用 `path.is_file()` 过滤，未知目录、目录 symlink 和 FIFO 不进入白名单集合，
因此有效 receipt 仍可被复用。

### 初次为何漏掉

实现把“普通文件白名单”错误实现成“先丢掉所有非普通文件，再检查剩余名字”，而不是检查目录中的全部
条目。初次测试只有额外普通 `candidate-2.json`，没有测试其他 inode 类型或合法文件名被换成 symlink。

### 根因与应如何思考

固定布局的集合运算对象必须是 `iterdir()` 的全部条目；文件类型本身也是契约的一部分。应先枚举全体，
再逐项要求“名称在白名单且 `lstat` 为普通文件”，不能用过滤器把攻击面隐藏掉。

### 修改

- 枚举 request journal 的全部目录项；
- 任何未知名称、目录、symlink、FIFO、设备或 lstat 错误均 fail-closed；
- 白名单内的 `intent/candidate/receipt` 也必须是实际普通文件，不允许 symlink。

### 生产反例与通过条件

额外目录、文件 symlink、目录 symlink、FIFO，以及把合法 `receipt.json` 换成 symlink 均零网络失败；完整
三个普通文件的 committed journal 继续零网络复用。

## 5. P1-4：IO 脱敏闭包不完整

### 现象

`os.link`、`fsync`、lock cleanup 和 verifier 的二次 Parquet 读取可把 token、Windows/WSL 私有路径及
chained cause 带入 traceback；cleanup 还可能掩盖原 provider permanent failure。

### 初次为何漏掉

原实现报告以 connector 和 writer-lock 已存在两个分支的结果，外推为“并发和 IO 的原始 OSError cause
均不进入 traceback”。实际并未逐一枚举 journal publication 生命周期和所有 Parquet 重读位置，也没有
注入 cleanup 失败。这是证据覆盖不足后的过度外推：局部 `from None` 不能证明全路径闭包。

### 根因与应如何思考

脱敏验收单位应是完整 IO 生命周期，而不是几个代表性异常。需要列出并逐一注入
`mkdir/open/close/link/fsync/unlink/read_parquet`，同时区分：

- 有主异常时，cleanup 只能尽力执行，不能替换主异常；
- 无主异常时，cleanup 失败必须抛稳定脱敏码；
- 只捕获预期 `OSError/PolarsError`，不使用 `BaseException` 吞业务契约错误。

### 修改

- journal root/request dir mkdir、lock open/close、atomic temp write/fsync/link、temp/lock cleanup 均建立窄的
  稳定错误边界；
- atomic publish 不覆盖语义不变；
- receipt/candidate/recovery 的 Parquet 重读统一经 `_read_parquet_sanitized`；
- `read_bytes/resolve/lstat` 的预期 IO 错误也切断 cause；
- lock cleanup 通过 `sys.exc_info()` 判断是否已有主异常：有则保留主异常，无则抛
  `JOURNAL_LOCK_CLEANUP_FAILED`；
- `RawStore` 新增 request 路径的 serialization/read/create 错误转换为无 cause 的稳定 `ValueError`，
  executor 再统一转换为稳定 `M3BackfillError`。

### 生产反例与通过条件

逐一注入 mkdir、open、close、link、fsync、unlink、直接及 chained Parquet OSError。每个反例同时扫描
`str(error)`、`repr(error)`、`traceback.format_exception(error)`，确认 token、client/private path 不出现。
provider permanent + unlink failure 仍返回 `TUSHARE_REQUEST_PERMANENT_FAILURE`；成功主路径的 unlink
失败返回稳定 cleanup code。

## 6. A13–A18 保持项

- A13：输入行序不改变逻辑 digest，重复行会改变 digest；
- A14：candidate 恢复时 connector、monotonic、sleep 全部禁用仍可成功；
- A15：连续两次 transient 在 base=2 秒时精确 sleep `[2.0, 4.0]`；
- A16：classifier 自身抛 chained 敏感异常时默认 permanent、不重试且完整脱敏；
- A17：真实 weekday sessions 精确取前 60/后 10，重复日历失败；
- A18：成分乱序/重复不改变完整 plan hash。

## 7. 额外实现自审

返工过程中发现两项未新增范围的实现风险并在原边界内修正：

1. 为 request raw 增加 Parquet 异常转换时，第一次补丁误命中了 legacy `RawStore.write` 的序列化分支，
   会改变旧 API 的异常表现。自审发现后已恢复 legacy 原代码，只在新增 `write_request` 路径保留脱敏；
   旧 API 幂等回归继续通过。
2. root preflight 后仍存在创建 journal/request dir 的小时间窗口。创建完成后增加二次 lstat/containment
   检查；`RawStore` 写入前再做第三层独立检查。不能消除所有外部恶意并发替换，但不会把“一次 preflight”
   误称为完整运行期锁定。

未发现需要修改 SSOT 或扩大到 mapper/B3/B4 的新设计阻塞。

## 8. 最终验证

全部命令均在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
90 passed in 6.75s

python -m pytest -q
391 passed, 1179 warnings in 14.11s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 仍为既有 Pandera/Polars deprecation warning，本次不把 warning 记为失败，也不把全量
pytest 绿色替代独立复验。

## 9. 剩余状态

- 未调用真实网络或 token；真实 Tushare SDK、真实 dtype 和完整历史范围仍未验证；
- 未实现 mapper、B3、B4 或 G1 release；
- B2A 仍为等待原独立初验 Agent 复验，不能写作 B2A/B2/G1/M3 通过；
- 未更新路线图或任何 Gate。

