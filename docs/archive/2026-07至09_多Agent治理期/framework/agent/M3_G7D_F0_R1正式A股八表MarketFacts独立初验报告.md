# M3 G7D-F0 R1：正式 A 股八表 MarketFacts 独立初验报告

日期：2026-08-09  
角色：全新独立初验 Agent（未参与实现）  
结论：**FAIL（P1 formal capability 来源闭包失效；返回返工）**

## 1. 独立性与范围

- 只读核对了任务单、实现交付、G7B 主验、`a_share_execution.py`、安全导出及实现者 formal 测试；生产代码与实现者测试未修改。
- 独立运行了 Windows 原生与 WSL base 定向测试、Ruff、mypy，并补充未落盘的 capability 伪造及 same-bytes root/file replacement 探针。
- 未联网、未读取 `data/legacy`、未触碰正式 G1、账户、journal 或 formal artifact；唯一新增文件为本报告。

## 2. 标准—证据—结论

- G1/G7B 顺序与八表读取边界：源码固定 `verify_g1_release -> verify_backtest_plan_artifact -> _read_formal_fact_files`，实现测试确认调用顺序；上游 hostile 异常被稳定翻译且 cause/context 为空。**通过（受本报告 P1 来源闭包问题约束）**。
- 八表 selector/schema/identity key/物理顺序：实现分别冻结 manifest identity key 与物理排序键，ledger 正确使用 manifest `(event_id)`、物理 `(symbol,ex_date,event_id)`；禁止排序修复。**通过源码核对**。
- E/S/D、生命周期、bar XOR FULL_DAY、PARTIAL、limit、benchmark/calendar 与 reconciliation 双向 closure：源码对冻结规则有直接 fail-closed 检查；实现 formal 测试双平台各 4 passed。**通过现有覆盖，但完整反例矩阵仍须在 R2 回归保持**。
- same-bytes entity replacement：独立临时目录探针对 same-bytes whole-root replacement 与 file replacement 均得到 entity snapshot 不相等。**通过底层实体探针**；本次未因首个 P1 再扩建完整 formal 发布物的调用窗口测试。
- portable identity：loader 生成值包含八个 full-file bytes digest、selected content digest、G1/G7B/window 锚并 whole-hash，且不含绝对路径/inode/PID/time。**生成路径通过源码核对**；但 public identity 接受 caller 任意填写的 `input_market_facts_sha256`，又能被下述公开构造器签成 exact formal capability，故消费侧来源闭包 **不通过**。
- capability 只能由 loader 最后一步签发、禁止公开八裸 frame formal 构造器：独立探针可直接读取模块 `_FORMAL_FACTS_SEAL`，传入 caller 自造 identity、八个空 DataFrame 与任意 `_provenance`，公开构造器成功返回 exact `VerifiedAShareMarketFacts`。随后 `object.__new__` 可复制全部 slots，并可替换 `_identity`。**不通过（P1）**。
- cold/runtime 与双平台静态质量：Windows/WSL 定向 Ruff、mypy 均通过；WSL 路径为 `/mnt/f` DrvFS，不是 ext4。**开发兼容证据通过，不是 Linux/ext4 Gate**。

## 3. P1 阻断问题

### 现象

caller 不调用 `load_verified_a_share_market_facts`，即可制造下游 exact-type 检查会接受的 formal capability：

```python
import quant.backtest.a_share_execution as m

forged = m.VerifiedAShareMarketFacts(
    identity=caller_identity,
    instruments=caller_frame,
    calendar=caller_frame,
    bars=caller_frame,
    limits=caller_frame,
    suspensions=caller_frame,
    corporate_actions=caller_frame,
    corporate_action_reconciliation=caller_frame,
    benchmark_bars=caller_frame,
    _seal=m._FORMAL_FACTS_SEAL,
    _provenance=object(),
)
assert type(forged) is m.VerifiedAShareMarketFacts
```

实际独立探针输出：

```text
True 6666666666666666666666666666666666666666666666666666666666666666 0
True True True
ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
```

第一行证明 module-private seal 直接签发 exact formal type，且任意 top-level portable hash 被接受；第二行证明 `object.__new__` + slots clone；第三行证明 clone 后 identity 可漂移。

### 根因

- `_FORMAL_FACTS_SEAL` 是可由 caller 读取的模块全局对象。
- public `VerifiedAShareMarketFacts.__init__` 本身就是八裸 DataFrame signer，`_provenance` 只存不验。
- capability 没有与 loader 完成 fresh 验证时生成的 process-local attestation 绑定；下游若只做 exact type，无法区分 loader 产物与 caller mint/clone。
- portable identity 的 `input_market_facts_sha256` 在 public 值对象构造时只校验 hex64，不按其他字段 whole-rehash；在上述 signer 存在时可把任意自报 identity 包装成 formal capability。

### 违反的规则或不变量

- 任务单第 2、7 节：“禁止公开裸八表 formal 构造器”“capability 只能由 loader 在最后一步签发”。
- formal capability 的核心来源闭包：八表必须来自同一 fresh G1 root，且必须在 fresh G7B 成功后才签发。
- exact type 是必要条件，不是来源证明；caller 提供的 `_provenance` 或自报 digest 不能充当 attestation。

### 最小复现

上方代码即最小复现；只需构造八个合法 shape 的 portable digest、一个 identity 和八个 `pl.DataFrame`，无需 G1、G7A、G7B、磁盘或 receipt。

### R2 必须新增的测试

1. caller 读取模块命名空间后，不存在可用于签发的 module seal/key/factory；用八裸 frames 直接调用 public class 必须失败。
2. `object.__new__` 空壳、从合法实例复制 slots、替换任一 frame/identity/provenance 后，在任一 public formal consumer 首行均被拒绝。
3. caller 自造或修改 portable digest、重复 `(root_alias, relative_path)`、任意 top-level hash、合法 whole-resign 均不能获得可消费 formal capability。
4. 合法 loader 产物必须绑定 process-local attestation；消费前重验 attestation 与八帧内容/portable identity whole-hash，mutation/clone 后 fail closed。
5. 保持现有 G1/G7B exact-once、G7B 前 CA 零读取、same-bytes file/root replacement、八表顺序、E/S/D、FULL_DAY/reconciliation、hostile 异常和冷导入回归。

### 通过条件

- 删除模块级可复用 seal/key/factory；public class 不再提供八裸 frame formal signer。
- loader 最后一步生成不可由 caller 参数替代的 process-local attestation，并将其与 exact identity、八表内容 digest 和物理 provenance 绑定。
- 所有 public formal consumer 在接受 exact type 前验证该 attestation并检测 constructor/new/clone/slot drift；失败统一稳定脱敏且零写入。
- 上述新增反例及既有 Windows/WSL 定向合同测试、Ruff、mypy 全部通过后，再交由另一全新独立上下文复验。

## 4. 实际验证

Windows 原生，worktree-local `PYTHONPATH=src`：

- `pytest tests/unit/test_m3_formal_a_share_market_facts.py -q`：**4 passed, 217 warnings, 4.26s**。
- 定向 Ruff：**All checks passed**。
- 定向 mypy：**Success: no issues found in 2 source files**。
- 一次扩大五文件 pytest 因承载层 240s 超时而未取得终态输出；确认子进程仍存活后未重复启动，随后自然退出。该次不记为通过或失败，也不影响上方明确定向结果与 P1 复现。

WSL Miniforge base，`/mnt/f/.../m3-g4-formal`、`PYTHONPATH=src`：

- 同一 formal facts pytest：**4 passed, 217 warnings, 2.88s**。
- 同一定向 Ruff：**All checks passed**。
- 同一定向 mypy：**Success: no issues found in 2 source files**。
- 该路径是 DrvFS/wslfs 兼容验证，**不是 ext4 Gate**。

warnings 为 Pandera Polars deprecation 与既有 `.pytest_cache` 权限告警；无本次代码诊断。

## 5. 结论

G7D-F0 R1 返回返工。除 formal capability 来源/attestation 闭包外，已检查的八表选择、窗口、公司行动闭包、实体 snapshot 和双平台定向质量证据未发现第二个阻断；但 P1 允许完全绕过 G1/G7B fresh 验证，当前不得进入主 Agent 最终验收，也不得解锁 G7C formal 返工。
