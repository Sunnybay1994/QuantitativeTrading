# M3 G1 B2A 请求计划与 Journal 二次返工交付报告

日期：2026-07-13  
独立复验：[`M3_G1_B2A请求计划与Journal独立复验报告.md`](M3_G1_B2A请求计划与Journal独立复验报告.md)  
第一次返工：[`M3_G1_B2A请求计划与Journal返工交付报告.md`](M3_G1_B2A请求计划与Journal返工交付报告.md)  
状态：原 P1-2 的 per-request raw 发现缺口已最小返工；等待独立二次复验，不代表 B2A/B2/G1/M3 通过

## 1. 边界与复现

本轮只修改原 B2A 的 `m3_backfill.py`、`storage.py` 和两个单元测试文件，并新增本报告。未修改独立报告、
SSOT、路线图或 Gate；未读取 `_old/`、本地 token 配置，未联网。

把独立复验的两个失败等价反例及 request path 变体转为生产测试。修复前新增后的定向结果为
**94 通过、4 失败**：

- request directory 自身是 symlink；
- request directory 内有未知目录；
- request directory 内有目录 symlink；
- request directory 内有 FIFO。

四类都会在最终写入防线失败，但 connector 已调用一次。request directory 自身为普通文件、额外 file
symlink 和未知普通文件已被原逻辑提前拒绝，因此修复前保持通过。

## 2. 为什么第一次返工仍遗漏

第一次返工正确补上了 raw/journal root 自身和既存祖先的联网前 `lstat`，也为 journal request directory
实现了全条目白名单；但 raw 恢复发现仍保留一段独立逻辑：

```python
directory.iterdir() if path.is_file()
```

这段代码先过滤非普通条目，再把过滤后的空列表解释成“没有 raw，可联网”。因此 root 和祖先虽然安全，
本次确定 request descendant 的现存布局却未闭合。根因不是缺少更多 root 检查，而是副作用前置检查只停在
root，没有递归到本次即将使用的确定路径，并且 executor 与 `RawStore` 各维护一套会漂移的目录状态规则。

今后的通用思考规则是：副作用前置验证应从控制 root 沿确定路径走到本次实际使用的叶子目录，并检查该
目录的全部现有条目；写入层再复用同一个状态检查作为二次防线。不能用 `is_file()` 过滤后再判断“空”。

## 3. 最小修改

### 3.1 单一 request-state 检查

`RawStore` 新增窄接口 `inspect_request_state`，复用既有 root/ancestor/descendant guard 和
`_controlled_request_entries` 的 `lstat` 语义，只有三种合法返回：

- `ABSENT`：request directory 不存在；
- `EMPTY`：request directory 是实际普通目录且没有条目；
- `COMPLETE`：目录精确包含两个实际普通文件 `data.parquet/metadata.json`。

以下状态不返回“无 raw”，而是稳定失败：

- request path 自身为 symlink 或非目录；
- data/metadata 单边；
- 任一未知普通文件；
- 任一额外目录、directory/file symlink、FIFO 或其他非普通 inode；
- lstat/枚举失败。

### 3.2 executor 与写入层复用

- `_recover_candidate` 在返回 `None`、允许 connector 调用前先调用 `inspect_request_state`；只有
  `ABSENT/EMPTY` 才视为可首次联网；
- `COMPLETE` 继续进入严格 raw 验真和零网络 candidate 恢复；
- 非法或孤儿统一返回稳定 `RAW_ORPHAN_OR_INVALID_LAYOUT` 且 `from None`；
- `RawStore.write_request` 和 `verify_request` 也改为消费同一状态接口，没有削弱二次防线；
- raw directory `mkdir` 后、首次 `_write_new_strict` 前再次要求状态精确为 `EMPTY`，缩小 post-mkdir
  替换窗口。

这仍不宣称能抵御检查完成后的内核级恶意并发替换；首版单 executor 威胁模型及独立报告记录的限制不变。

## 4. 五态生产回归

| 状态 | 生产证据 | 预期结果 |
|---|---|---|
| 目录不存在 | 正常首次执行 | 允许一次 connector 调用并形成完整 journal/raw |
| 合法空实际目录 | 预创建空 request directory | 允许一次 connector 调用 |
| 完整 data+metadata | 既有 after-metadata 故障注入 | 重跑 connector/clock/sleep 为 0，恢复 candidate/receipt |
| 单边 data 或 metadata | 既有两类孤儿测试及 after-data 故障注入 | connector/clock/sleep 为 0，稳定失败 |
| 非法布局 | request symlink/普通文件、未知目录/文件、dir/file symlink、FIFO | connector/clock/sleep 为 0，稳定脱敏失败 |

所有非法布局反例还扫描 `message/repr/traceback.format_exception`，不包含测试临时路径；request directory
symlink 指向的外部目录保持为空。合法 committed receipt/candidate 零网络恢复测试继续通过。

## 5. 验证结果

全部命令在 WSL Miniforge base 运行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
98 passed in 6.48s

python -m pytest -q
399 passed, 1179 warnings in 12.78s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 仍为既有 Pandera/Polars deprecation warning。未发现需要修改 SSOT 或扩大到 mapper/B3/B4
的新设计问题。

## 6. 状态

- 未联网、未读取 token；
- 未修改路线图、Gate 或其他任务包；
- 当前只可写“等待独立二次复验”，不得宣称 B2A、B2、G1 或 M3 通过。

