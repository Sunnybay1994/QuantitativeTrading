# M4 P8 RUN-0B2B：Formal A股 PAPER Policy/Config Loader 交付报告

日期：2026-08-09  
状态：实现与自验完成；待独立初验与主 Agent 终验

## 1. 交付结果

按重冻任务书新增只读、零网络、零状态写入的 formal A股 PAPER policy loader：

- formal capability 只接受 exact `VerifiedPaperRuntimeEnvironment` 与 allowlisted
  `paper_a_share_v1` selector；development/example/path/unknown selector 在读取业务文件前稳定拒绝；
- 唯一来源固定为 verified project root 下的 versioned policy 文件；project、parent、file 使用 anchored
  open-instance、physical identity、单链接 regular file、内容 SHA 与签发前 held-descriptor 复读闭包；
- 嵌套 TradingConfig 复用现有构造器和 identity，费用复用
  `ExecutionCostPeriod`、`build_execution_cost_schedule`，最小经济金额复用 `MoneyAmount`；
- exact SH/SZ、CNY、2026 open-ended window、risk/store/fee/rule/version selectors 全部按任务书验证；
- 唯一私有 closure mint 用 process-local attestation 绑定 retained TradingConfig、cost schedule、minimum
  notional、source identity、session 与 runtime verification identity；existing verifier fresh 调公共 loader 后
  exact compare；
- 公开错误只输出五类稳定码，内部 hostile path、SQL、TOKEN、parser/builder 异常不进入 cause、context 或 repr。

## 2. 文件范围

- 新增 `src/quant/execution/paper_policy.py`
- 新增 `configs/trading/policies/paper_a_share_v1.toml`
- 新增 `configs/trading/policies/paper_a_share.example.toml`
- 新增 `tests/unit/test_paper_policy.py`
- 更新本任务单状态
- 新增本交付报告

未修改 runtime、broker、gateway、service、CLI、store/migration、P4-P8、soak 或 package root；未创建正式
runtime root、数据库、journal、receipt、缓存，未发起网络请求。

## 3. 对抗覆盖

测试覆盖：

- 2026-01-01 边界日与普通 session 的 exact SH/SZ policy、fresh existing；
- development/example/unknown/path traversal selector；伪 runtime、缺失 attestation、hostile runtime verifier；
- TOML unknown/duplicate/invalid UTF-8、noncanonical decimal/float、store/mode/market/coverage 漂移；
- symlink、hardlink、同 bytes 换 inode、same-inode persistent drift；
- retained TradingConfig/cost identity 及 nested object replacement 后沿用旧 attestation；
- hostile TradingConfig/cost builder 异常脱敏；模块表面无 generic signer、factory 或模块级 32-byte key。

## 4. 验证证据

Windows 原生 Miniforge，worktree `PYTHONPATH=src`：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_policy.py -q
27 passed, 1 skipped in 3.83s

D:\Miniforge3\python.exe -m ruff check \
  src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
All checks passed!

D:\Miniforge3\python.exe -m mypy \
  src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
Success: no issues found in 2 source files

Windows cold import + forbidden-module absence: PASS
```

唯一 Windows skip 是当前主机未授予 symlink 创建权限；hardlink、anchored identity 与其他 source 反例通过。

WSL Miniforge base，路径位于 DrvFS：

```text
python -m pytest tests/unit/test_paper_policy.py -q
28 passed in 2.80s

python -m ruff check src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
All checks passed!

python -m mypy src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
Success: no issues found in 2 source files

WSL base cold import: PASS
```

## 5. 诚实边界

- 当前 WSL 路径是 DrvFS；以上只证明双平台开发契约兼容，不代表 WSL2/ext4 formal Gate 已关闭。
- 自验中的 formal happy path 是纯合同 fixture，并通过测试内隔离 runtime fresh verifier；没有伪造或产生
  `VerifiedPaperRuntimeEnvironment` 正式产物。
- 本包没有实现 fill/fault 算法、gateway/store/service factory、TargetLoader、LedgerContextProvider、scheduler
  或 soak；只交付后续 formal 装配的 policy 输入。
- worktree 含大量前序里程碑既有脏文件与测试目录；本轮只写任务白名单文件，未清理、暂存或提交其他改动。

