# M3 G7D-F0 R3 public loader closure 与 reload 隔离主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；允许解锁 G7C 实现**  
边界：formal 八表 MarketFacts 工程合同通过；不是完整真实 work、Linux/ext4 或 M3 Gate

## 1. 验收结论

R1 的模块级 seal/裸八表构造旁路、R2 的 public loader closure 暴露 prepared-facts mint，以及 reload 测试污染
后续类型身份，均已通过 R3 闭合：

- formal exact class 与 public loader 由一次性初始化过程产生，模块表面无旧 seal/key/generic mint/factory；
- public loader 的可达 callable graph 不包含接受 identity/frames/provenance 的 prepared-facts签发入口；
- 唯一执行 raw allocation 的 callable 是完整四参数public loader，并且每次先走G1/G7B/八表完整prepare；
- 内容证明绑定 identity、八帧schema/物理顺序/全内容、portable whole hash、process-local provenance与实例登记；
- constructor、未登记`object.__new__`、slots clone、identity/frame/provenance/nonce/hash/证明字段漂移均在任何
  property/repr返回前失败；属性只返回frame clone；
- reload旧对象测试已迁入fresh subprocess，固定顺序reload后development facts/G7B/G7E不再受污染；
- R1八表窗口、E/S/D潜在持仓域、生命周期、bar XOR FULL_DAY、limit/benchmark、ledger-reconciliation event-set、
  same-bytes root/file replacement合同保持不变。

独立R3复验遍历18个可达callable，只有完整public loader执行allocation；新增本地QA与双平台回归均PASS。
报告如实保留边界：同进程任意读取/篡改非callable closure cell不属于任务§12冻结范围，本验收不把Python对象
描述为加密不可伪造或外部信任根。

## 2. 主 Agent 实际验证

Windows `D:\Miniforge3\python.exe`、worktree-local `PYTHONPATH=src`：

- `test_m3_formal_a_share_market_facts.py`：`23 passed`；
- 定向 Ruff：PASS；
- 定向 mypy 2 source files：PASS。

WSL Miniforge base `/mnt/f/.../m3-g4-formal`：

- 同一formal文件：`23 passed`；
- 定向 Ruff：PASS；
- 定向 mypy 2 source files：PASS。

WSL组合命令中的mypy 2.2.0首次报一次无业务诊断的`INTERNAL ERROR`；未重跑已通过的pytest/Ruff，单独以
相同2文件、`--no-incremental --show-traceback`复核后`Success: no issues found`。该瞬时工具错误已如实保留。

实现R3额外固定顺序组Windows/WSL各`26 passed`；独立复验同样取得23+26及Ruff/mypy/cold-import双平台
绿证据。主验未机械重复全部邻接长套件。

## 3. 状态与边界

G7D-F0 R3标记主验PASS，G7C前置满足。当前WSL为`/mnt/f` DrvFS，不是ext4；正式全work性能、G7C-G9、
Linux/ext4与M3 Gate仍开放。未联网、未add/commit、未触碰正式G1 artifact/journal；既有无关脏文件保持原样。
