# M1 SSE-E2 单 Route Clean 事件原子重建任务单

## 1. 目标

SSE-E1 已修复事件方向 mapper，但现有 SH clean 事件由旧 mapper 生成。因为普通 upsert 的唯一键包含 action，
纠正后的 ADD 会与旧错误 REMOVE 并存。新增显式、受控的单 route clean replace 能力；本包只实现代码和 fake
测试，不联网、不改项目真实 data。

## 2. 冻结合同

### Store

`CleanConnectEventStore.replace_route(frame: pl.DataFrame) -> int`

1. 先以 `ConnectEligibilityEventSchema` 严格验证；frame 必须非空且只含一个精确 route；非法输入在目标文件
   任何变化前拒绝。
2. 只原子替换 `root/route=<route>/data.parquet`，按 `effective_date,symbol,action` 排序；不得 concat 旧文件。
3. 另一 route、raw、snapshot、calendar、universe 文件零变化。
4. 写后重新读取并过 Schema，行数和业务键集合必须与输入一致；失败不得宣称成功。

### Pipeline/CLI

1. `ConnectMarketPipeline.update_events(*, replace_clean: bool = False)`；严格 bool。False 保持原 upsert；True 只
   调用 event store `replace_route`。不改变 snapshot/calendar 路径。
2. `update_connect` 新增 `--replace-clean`，只允许与 `--table events` 同用；非法组合必须在 connector 构造和
   网络/FS 副作用前拒绝。
3. 执行顺序保持：fetch official raw → immutable RawStore.write → mapper/schema → replace route clean。mapper 或
   clean 验证失败时 raw 可保留，但原 clean route 必须不变。
4. CLI JSON 增加 `clean_mode`，严格为 `UPSERT` 或 `REPLACE_ROUTE`；不输出绝对 token/凭据。
5. 默认命令行为不变；禁止自动 replace、自动重建 universe 或扩大到其他 route。

## 3. 文件白名单

- `src/quant/data/storage.py`
- `src/quant/data/connect_market.py`
- `src/quant/data/update_connect.py`
- `tests/unit/test_storage.py`
- `tests/unit/test_connect_market.py`
- `tests/unit/test_update_connect.py`
- `README.md`（仅新增安全用法与警告）
- `docs/agent/M1_SSE-E2单RouteClean事件原子重建交付报告.md`

若现有测试文件名不同，允许使用同模块现有测试文件，但不得新改其他生产模块。

## 4. 必测反例

- replace 后旧错误 action 行彻底消失，而非与新行并存；
- 替换 SH 时 SZ 文件字节/mtime 不变；
- 空 frame、多 route、非法 Schema、`replace_clean=1/True` 类型边界（True 合法、1 非法）在 clean 变化前失败；
- mapper 混入未知 ADJUST_TYPE：raw fake 可记录，但旧 clean 字节不变；
- CLI `--replace-clean --table snapshot/calendar` 在 connector/network/FS 前失败；
- 默认无 flag 仍走 upsert；显式 flag 只走 replace_route；
- 重复用同一合法 frame replace，结果内容确定且无重复。

## 5. 验证

WSL Miniforge base，最小 tmp/fake：

```bash
python -m pytest tests/unit/test_storage.py -q -k 'connect and (event or replace)'
python -m pytest tests/unit/test_connect_market.py -q
python -m pytest tests/unit/test_update_connect.py -q
ruff check src/quant/data/storage.py src/quant/data/connect_market.py src/quant/data/update_connect.py tests/unit/test_storage.py tests/unit/test_connect_market.py tests/unit/test_update_connect.py
mypy src/quant/data/storage.py src/quant/data/connect_market.py src/quant/data/update_connect.py
```

禁止真实网络、项目 data、全量 pytest、Git 初始化。实现与独立初验使用不同全新
`cursor-grok-4.5-high` 会话。独立初验除唯一报告外代码只读，须补“替换目标是 symlink/非普通文件时
fail-closed 且外部文件不变”的 `/tmp` 对抗；若当前存储层没有可信路径防护，初验必须判失败并回到返工，
不得把它降为小问题。

唯一初验报告：`docs/agent/M1_SSE-E2单RouteClean事件原子重建独立初验报告.md`。
