# M3 G7D-F0 R3：public Loader Closure 与 Reload 隔离返工交付报告

日期：2026-08-09  
角色：返工实现 Agent  
状态：**R3 返工与双平台自测完成，待独立复验；不宣称 G7/M3/Linux ext4 Gate 通过**

## 1. R2 问题与 R3 最小修复

R2 的 HMAC、whole hash、issued-instance registry、property 前重验，以及 R1 的八表/窗口/root/FULL_DAY 语义
全部保留。本轮仅关闭两处边界：

- 删除 public loader closure 中可直接调用的 `mint(identity, selected, provenance)`。
- raw instance allocation、八帧 clone、slot 赋值、attestation 和 issued registry 登记全部内联到 public loader 的
  一次完整调用栈；此前必定先执行 `_prepare_verified_a_share_market_facts` 的 G1→G7B→八表 fresh 闭包。
- public loader 与 class property/repr 的递归 callable closure 图中，不再存在接受 identity、frames、selected 或
  provenance 的 callable。唯一具有 `release, plan, fresh_context, artifact_roots` 完整签名且能签发的 callable 是
  public loader 本身。
- `_prepare_verified_a_share_market_facts` 仍是普通值准备函数；直接调用只返回 identity/selected/provenance
  三元组，既不分配 formal 对象，也不登记 issued registry。
- reload 反例改为 fresh subprocess；主 pytest 进程不再 reload 生产模块，因此不会污染后续 formal/development
  类型身份。

## 2. R3 新增对抗

`tests/unit/test_m3_formal_a_share_market_facts.py` 现为 23 项：

1. 从 public loader、九个 property getter 与 repr 出发，递归枚举传递 callable closure cells；
2. 断言所有可达 callable 均无 prepared-facts 参数，并以伪 raw identity/frames/provenance 尝试逐一调用；
3. 断言唯一完整 public-loader 参数集合对应 public loader 本身；
4. 调用普通 prepare 后 `object.__new__` 伪对象仍未登记，随后 public loader 再独立执行一次 prepare 才签发；
5. reload/旧 capability 反例在 fresh subprocess 完成并检查稳定空 cause/context；
6. 固定顺序 `reload subprocess test → development facts → G7B → G7E` 在同一父 pytest 进程回归。

冻结威胁模型边界：R3 关闭的是 §12 指定的 callable closure 攻击面。Python 对任意非 callable closure cell 的
进程内反射/内存篡改不在该冻结探针内；这不改变 R2 已冻结的 process-local capability 边界。

## 3. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，隔离 `PYTHONPATH=src`：

```text
Ruff（两个生产文件 + formal facts 测试）          PASS
mypy（两个生产文件）                              PASS
R3/R2/R1 formal facts 完整测试                     23 passed / 23.03s
固定顺序 reload→development facts→G7B→G7E       26 passed / 152.70s
cold import、无模块 mint、无 Qlib/LightGBM/MLflow PASS
```

WSL Miniforge base：

```text
Ruff（两个生产文件 + formal facts 测试）          PASS
mypy（两个生产文件）                              PASS
R3/R2/R1 formal facts 完整测试                     23 passed / 19.39s
固定顺序 reload→development facts→G7B→G7E       26 passed / 64.10s
cold import、无模块 mint、无 Qlib/LightGBM/MLflow PASS
```

warnings 仅为既有 Pandera Polars deprecation 与工作区 `.pytest_cache` 权限告警。WSL 工作区解析到 `/mnt/f`，
只构成 DrvFS 兼容证据，不是 ext4 Gate。白名单 `git diff --check` 通过。

## 4. 白名单与剩余验收

- R3 仅修改 `src/quant/backtest/a_share_execution.py`、既有 formal facts 测试、任务状态并新增本报告；
  `src/quant/backtest/__init__.py` 的 R1 导出保持不变。
- 未修改 R1/R2 交付报告或任何独立初验报告；未联网、add、commit、写正式 artifact/journal 或触碰正式 G1。
- 工作树其他既有脏文件与临时目录保持原状。
- 当前仅为实现自测通过，仍待全新独立上下文按 §12 复验 callable graph、prepare 调用计数和 reload 顺序隔离。
