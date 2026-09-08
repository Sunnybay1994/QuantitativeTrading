# M4 P0-H1 可信 SQLite 根目录独立初验报告

状态：**独立初验通过，可交主 Agent**（不宣称 P0/M4 Gate 通过）  
日期：2026-07-17  
身份：全新外部只读初验 Agent（未参与实现）  
模型：cursor-grok-4.5-high（非 fast）  
任务单：[M4_P0-H1可信SQLite根目录实现任务单.md](M4_P0-H1可信SQLite根目录实现任务单.md)  
交付报告：[M4_P0-H1可信SQLite根目录交付报告.md](M4_P0-H1可信SQLite根目录交付报告.md)  
对照：[M4_P0主Agent最终验收报告.md](M4_P0主Agent最终验收报告.md)

## 1. 范围与纪律

- 只读核对 src/quant/execution/store.py、tests/unit/test_execution_store.py 与交付映射；未改生产代码、实现测试、配置、任务书、路线图。
- 未读写任何 B2 文件/报告。
- 未跑全量 pytest；未联网；未读 token/真实数据/data/。
- 项目命令均在 WSL /mnt/g/BaiduSyncdisk/wsl/Cursor/quant 的 Miniforge base 执行。

## 2. 任务单 2-9 逐项核对

| 条款 | 结论 | 证据摘要 |
|---|---|---|
| open(uri, *, trusted_root) 强制 keyword-only，缺省 TypeError | 通过 | 签名 uri + KEYWORD_ONLY trusted_root；缺省调用 TypeError；模块无 Path.cwd/os.getcwd |
| lexical URI 不放宽；_parse_sqlite_uri 返回相对 Path | 通过 | 解析规则保留；返回相对 Path；既有 F1 非法 URI 仍为 URI_INVALID |
| trusted_root 类型/绝对/存在/目录/非 symlink/非文件系统根/resolve(strict=True) | 通过 | _validate_trusted_root；实现者 H1 用例覆盖 str/bytes/bool/fspath/子类/相对/symlink/文件/根 |
| 失败码 TRUSTED_ROOT_INVALID，无路径泄露，cause/context 空 | 通过 | 实现者 scrub 断言 + resolve OSError 脱敏用例 |
| 祖先逐段禁 symlink/非目录/出界；缺失可建后复验 | 通过 | _materialize_db_path + _check_existing_dir_component；含 root 内 symlink 仍拒 |
| leaf 普通单硬链接文件；目录/FIFO/symlink/多硬链接拒绝 | 通过 | _check_leaf（S_ISREG 且 st_nlink==1） |
| connect 后复验失败先 _safe_close 再抛；close 失败不覆盖主错 | 通过 | open post-check 路径；实现者用例 + 本会话 8.3 独立探针 |
| containment 用物理 resolved/relative_to，非路径 startswith | 通过 | _is_within_root 使用 relative_to |
| 失败码 URI_PHYSICAL_BOUNDARY_INVALID，脱敏、空链 | 通过 | 定向测试与独立探针 |
| 既有 open 改显式 root；tmp_path only | 通过 | _open(..., trusted_root=)；无 data/ 读取 |
| 白名单 | 通过 | 交付仅列 store.py / test_execution_store.py / 交付报告；初验未越权 |
| 定向 pytest/ruff/mypy | 通过 | 见第 3 节 |
| 至少三独立反例（含三项指定） | 通过 | 见第 4 节 |
| 不勾选路线图、不宣布 Gate | 遵守 | 本报告仅结论“可交主 Agent” |

特别核对：

- 无 trusted_root 导致 TypeError：通过
- cwd 不影响落点：通过（实现者用例 + 独立 chdir 探针）
- 祖先/leaf symlink：通过（含 8.1 两层祖先第二层外指）
- hardlink/special file：通过（含 8.2 合法 DB 被换成 hardlink）
- connect 后复验 + close 双失败：通过（8.3）
- 错误 cause/context/traceback 脱敏：通过
- 未削弱原 schema/事务合同：通过（见下）

## 3. 定向验证（WSL Miniforge base）

```text
python -m pytest tests/unit/test_execution_store.py -q
-> 130 passed

python -m ruff check src/quant/execution/store.py tests/unit/test_execution_store.py
-> All checks passed

python -m mypy src/quant/execution/store.py
-> Success: no issues found in 1 source file
```

收集计数：共 130；其中 test_h1_* 20 项，非 H1 110 项。相对原 P0 主验“109 passed”，非 H1 现为 110（多 1 项，疑为边界码对齐下的目录-as-db 用例保留/显式化），未见删减或弱化 identity/FK/事务/migration/脱敏合同；文件祖先在既已存在非目录时映射为 URI_PHYSICAL_BOUNDARY_INVALID，与任务单第 4 节一致；真实 mkdir OSError 仍映射 PARENT_CREATE_FAILED。

## 4. 实现者未使用的对抗性反例（第 8 节三项，临时目录探针）

探针脚本仅写于 WSL /tmp/h1_ind_probe.py，未写入仓库。结果：SUMMARY PASS。

| # | 反例（实现者未用形态） | 结果 |
|---|---|---|
| 8.1 | L1/ 真实目录 + L1/L2 指向 root 外 symlink，leaf ghost.db 不存在 | URI_PHYSICAL_BOUNDARY_INVALID；外部未建库；cause/context 空；路径不泄露 |
| 8.2 | 先合法打开并关闭 DB，再将 leaf unlink 后 os.link 成 hardlink；monkeypatch 计数 sqlite3.connect | 拒绝且 connect 调用次数=0；硬链接目标内容/mtime/size 未变 |
| 8.3 | connect 后武装 _check_existing_dir_component 抛含绝对路径 OSError（父目录复验，异于实现者 mock _check_leaf），同时 wrapper close 抛另一路径泄露 | 主错仍为 URI_PHYSICAL_BOUNDARY_INVALID；close 被调用 1 次但不覆盖；两条泄露路径与 root 均不出现在 message/repr/traceback；cause/context 均为 None |

额外独立探针：API keyword-only、模块无 cwd、解析相对路径、chdir 后仍落在 trusted root——均通过。

## 5. 与原 P0 主验边界的关系

原主验已通过 lexical URI / identity / FK / 事务脱敏，并记录 P2：RELATIVE_SYMLINK_ESCAPE。本包关闭该静态 symlink/hardlink 逃逸面；不因此重新宣布原 P0 子包或 M4 Gate 状态变化。TOCTOU/同账户并发 rename 仍按任务单限制，不在本包宣称范围内。

## 6. 结论

独立初验通过。P0-H1 交付满足任务单冻结契约与第 8 节对抗要求，可交主 Agent 最终验收。

初验 Agent 不宣称 P0/M4 Gate 通过，不勾选路线图。