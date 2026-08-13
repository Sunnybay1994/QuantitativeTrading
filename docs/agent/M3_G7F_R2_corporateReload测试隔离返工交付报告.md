# M3 G7F R2：corporate reload 测试隔离返工交付报告

日期：2026-08-10
状态：**R2 tests-only 返工与双平台自测完成，待未参与 R2 的全新独立上下文复验**

## 1. 交付结论

已按任务单 §16 完成 tests-only 最小返工。`test_corporate_action_core_import_does_not_load_qlib` 的 cold import
与 reload 合同现全部在 fresh、`-I` 隔离的 subprocess 中执行；主 pytest 进程不再 reload 已被 G7E simulator
等 consumer 导入的 `quant.backtest.corporate_actions` module，因此不会制造新旧 enum/state/transition identity
分裂。

本轮未修改任何 production、G7E/G7F 测试或 formal exact-type 语义。本报告只声明实现者返工和自测完成，
不声明独立复验、主验、G7F、G8、ext4 或 M3 Gate PASS。

## 2. 现象、根因与应遵循规则

R1 独立初验的原顺序153项为 `148 passed / 5 failed`。先收集并导入 G7E simulator 后，旧测试在主 pytest
进程内对 corporate-actions 原地 `importlib.reload`；module dict 被新 enum 与 opaque capability identity 替换，
而 consumer 仍持有 reload 前 identity，后续 actual G7E 被正确的 exact boundary fail-closed。

应遵循规则是：测试 import/reload 隔离不得改变其他已收集测试共享的 production module identity。reload 行为本身
仍要测试，但只能置于 fresh subprocess；不得通过放宽 exact type、改顺序、排除节点或拆分153项掩盖污染。

## 3. 最小修改与保留合同

唯一代码修改为 `tests/unit/test_m3_corporate_actions.py`：

- 父 pytest 只拼装脚本并启动 fresh `python -I -c` subprocess；
- 子进程显式使用当前工作树 `src`，导入前后均断言 `qlib/lightgbm/mlflow` 未加载；
- 子进程 exact 断言 corporate-actions `__all__` public surface，且私有 issuer 不可达；
- reload 前签发旧 state/transition，reload 后断言两者稳定拒绝且异常 `cause/context=None`；
- reload 后重新签发 exact 新 state/transition，完成 pre-open advance 与公开 mark 计算，证明新 capability 可用；
- 原 fixed-order 测试名称和原153项文件顺序均未修改。

## 4. SHA 零变化证据

以下 production/G7F tests 在 R2 前后 SHA-256 相同，本轮没有写入：

- `a_share_reporting.py`：`698937e25ae69505497565fe65722e4e694ae2b7b00e50ecf0370332085b3a81`；
- `a_share_simulator.py`：`2e123bc293137b468307bd64bd8ede2f4bbbced0ba48b487596461f235605406`；
- G7F unit：`b3a28fec24d63f02e259fd1a11e9779b04976976c0ef9986718a0e9b81866a3e`；
- G7F golden：`3b13fe167e8586e014ec530c578e2e853d9d513e1ea36caacaf1b639e2f150ce`。

## 5. 验证证据

Windows Miniforge，最终 revision：

- isolated cold/reload 单节点：`1 passed`；
- 固定顺序 cold 节点 → G7E 正向 → hostile Decimal → golden：`4 passed`，`147.53s`；
- 独立初验原8文件原顺序、单一 pytest 进程：`153 passed`，`675.07s`；
- G7F unit + golden：`10 passed`，`465.71s`；
- 定向 Ruff、mypy 与 cold import：通过。

WSL Miniforge `base`，最终 revision：

- 固定顺序 cold 节点 → G7E 正向 → hostile Decimal → golden：`4 passed`，`119.11s`；
- 独立初验原8文件原顺序、单一 pytest 进程：`153 passed`，`460.26s`；
- G7F unit + golden：`10 passed`，`380.24s`；
- 定向 Ruff、mypy 与 cold import：通过。

`git diff --check` 通过；测试只有 Pandera/Polars 已知 deprecation warnings。WSL 工作树位于 `/mnt/f` DrvFS，
因此仅作双平台兼容证据，不声明 Linux/ext4 Gate。

## 6. 文件范围与下一步

R2 只修改：

- `tests/unit/test_m3_corporate_actions.py`；
- G7F 任务单状态；
- 本唯一 R2 交付报告。

未修改 production、G7E/G7F tests、contracts、schemas、config、正式 artifact；未联网、add、commit 或发布。
下一步必须由未参与 R2 的全新独立上下文按相同 fixed-order 与153项集合复验，PASS 后才可交主 Agent 主验。
