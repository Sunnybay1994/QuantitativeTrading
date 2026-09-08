# M3 G1-R1A 首次独立初验会话停滞接管任务单

日期：2026-07-15  
状态：**接管完成；发现的 TOCTOU 缺陷已返工、复验并通过主验**  
执行模型：非 fast `cursor-grok-4.5-high`

## 1. 接管原因与证据资格

首次 R1A 独立初验会话于 2026-07-15 19:41 启动。约 80 分钟后仍无
`docs/M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md`，当时无任何 WSL pytest/Ruff/mypy 子进程，
Windows Node CPU 长时间不变。主 Agent 判定会话停滞并仅终止该 R1A Node；同期 R1L 独立初验会话未受
影响，且已独立通过。

首次 R1A 会话没有交付报告，其过程、自测和可能的临时结论全部不具备证据资格。接管 Agent 必须是全新
会话，从冻结任务书和已交付文件重新独立验证，不得把首次会话视为前置通过或复验。

## 2. 权威输入

- `AGENTS.md` 与 `karpathy-guidelines.md`
- `docs/M3_G1_R1A运行身份与分阶段计划骨架外部闭环任务单.md`，尤其 §4–§10
- `docs/M3_G1_R1A运行身份与分阶段计划骨架交付报告.md`
- `docs/M3_G1_R1A合流mypy单点返工任务单.md`
- `docs/M3_G1_R1A合流mypy单点返工交付报告.md`
- `docs/M3_G1_R1L崩溃安全Journal写锁独立初验报告.md`（只用于确认合流状态，不代替 R1A 验收）

## 3. 文件与角色边界

唯一允许写入：

```text
docs/M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md
```

生产代码、实现者测试、配置、其他文档、数据与产物全部只读。不得修复发现的问题；失败时按六项格式写入
报告并交回外部实现闭环。不得宣称 R1A/G1/M3/Gate 通过。

## 4. 必做独立验证

重新逐项映射原任务书冻结合同，并完成原 §9 的五项未公开对抗：

1. source 文件在 hash 完成后、返回前被同大小 inode 替换；
2. 伪造自洽但不等于 C0 重算值的 `LoadedM3Config`；
3. index response 集整体替换为另一套 request/receipt/frame 自洽对象；
4. observation 加入早期已调出证券，证明 history union 不退化为结束日截面；
5. runtime dependency tuple 使用大小写别名或 Unicode 控制字符碰撞。

临时对抗脚本只能置于项目外临时目录，结束后不得留在 `src/` 或 `tests/`。所有项目命令通过 WSL
Miniforge `base`，禁止 Windows Python。

## 5. 重检查与 usage 边界

刚完成且代码未再变化的合流证据是：全量 `832 passed`、Ruff 通过、mypy 81 个源文件通过；R1L 初验又在
持久锁下通过了全量 mypy。接管 Agent 不重复约 50 分钟的全量 pytest，而是在不得 unlink 的
`/tmp/quant-m3-r1-validation.lock` 下串行执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_g1_planning.py tests/unit/test_m3_config.py \
  tests/unit/test_m3_backfill_requests.py tests/unit/test_index_membership.py
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/research/m3/g1_planning.py src/quant/research/m3/__init__.py \
  tests/unit/test_m3_g1_planning.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

报告必须明确区分“本会话实跑的定向/静态验证”和“复用的外部实现全量 832 证据”。

## 6. 通过条件

- 五项未公开对抗全部有可复现证据；
- 冻结合同逐项映射无缺口；
- 定向 pytest、Ruff、mypy 全部退出码 0，持久锁仍存在；
- 唯一写入初验报告；
- 结论仅为“初验通过，可进入主验”，或按六项格式明确“不通过，返回外部实现返工”。
