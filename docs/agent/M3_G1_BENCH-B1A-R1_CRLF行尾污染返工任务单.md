# M3 G1 BENCH-B1A-R1：CRLF 行尾污染返工任务单

## 1. 现象

B1A 外部实现与 Windows 自测完成后，主 Agent 在 WSL 仓库执行 `git diff --check`，发现
`tests/unit/test_m3_backfill_requests.py` 的所有新增行均被报告为 `trailing whitespace`。`file` 与字节审计
确认该文件当前 2115 个换行全部为 CRLF；同包其余 Python 测试文件为 LF。

冻结证据：

- 当前 raw SHA-256：`944dced7d51df7feb85fb866d297c60a2968f96e61d1dc36a6857579b33f3c85`
- 仅把 `CRLF` 替换为 `LF` 后的预期 SHA-256：
  `83713a5d7ad392282a7d6db89878d5375c3439c8d799f5e13ea73cdf78291178`
- 逻辑行数：2115；CRLF：2115；bare CR：0

## 2. 根因与应遵循规则

根因是实现会话在 Windows 写回该测试文件时把整文件行尾转换为 CRLF。Windows pytest/Ruff/mypy 未把该
格式漂移作为失败，而 WSL Git 的 whitespace Gate 会对新增 `\r` fail closed。

应遵循：仓库既有 LF 格式必须保持；跨 Windows/WSL 写入后必须在 WSL 执行 `git diff --check`。格式化或
编辑工具不得无关地转换整文件行尾。

## 3. 最小复现

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading
file tests/unit/test_m3_backfill_requests.py
git diff --check -- tests/unit/test_m3_backfill_requests.py
```

返工前第一条显示 `with CRLF line terminators`，第二条报告新增行 `trailing whitespace`。

## 4. 最小返工与白名单

实现 Agent 只允许：

1. 将 `tests/unit/test_m3_backfill_requests.py` 的全部 CRLF 机械转换为 LF；
2. 不改变任何可见字符、测试逻辑、导入、顺序或断言；
3. 写唯一报告
   `docs/agent/M3_G1_BENCH-B1A-R1_CRLF行尾污染外部返工交付报告.md`。

其余生产代码、测试、配置、既有交付报告和文档均只读。不得运行真实网络或 Tushare。

## 5. 新增回归检查与通过条件

本格式事故的新增回归检查是 WSL Git whitespace Gate，不增加无关 Python 单测：

- 修复后文件 raw SHA-256 必须精确为
  `83713a5d7ad392282a7d6db89878d5375c3439c8d799f5e13ea73cdf78291178`；
- LF 数为 2115，CRLF 与 bare CR 均为 0；
- `git diff --check -- tests/unit/test_m3_backfill_requests.py` 零输出、退出码 0；
- `python -m pytest tests/unit/test_m3_backfill_requests.py -q` 通过；
- `ruff check tests/unit/test_m3_backfill_requests.py` 通过。

返工交付后必须由一个未参与返工的全新外部 Cursor 会话只读复验，并写
`docs/agent/M3_G1_BENCH-B1A-R1_CRLF行尾污染外部独立复验报告.md`；复验通过后才回到 B1A 主验。
