# M3 G7D-F0 R2：内容绑定 Capability 来源闭包独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的独立复验 Agent  
结论：**FAIL（P1：公开 loader 的 Python closure 暴露内部 `mint`，仍可绕过 G1/G7B fresh 验证签发 exact formal capability）**

## 1. 独立性、范围与证据边界

- 只读核对了 `AGENTS.md`、通用工程规则、任务单第 11 节、R1 独立初验报告、R2 返工交付报告、`src/quant/backtest/a_share_execution.py` 与 `tests/unit/test_m3_formal_a_share_market_facts.py`。
- 生产源码和实现者测试全程只读；唯一写入是本报告。
- 未联网，未读取或写入 formal 数据、正式 G1、账户、journal、凭据或 `data/legacy`；未执行 `git add`、commit 或 push。
- 独立新增反例全部在 Python 进程内构造，未落盘临时源码或 formal artifact。
- WSL 工作树位于 `/mnt/f/.../m3-g4-formal`；`findmnt` 返回 `drvfs`，**不是 ext4**。因此 WSL 结果仅是 DrvFS/Linux runtime 兼容证据，不是 Linux ext4 Gate。

## 2. 第 11 节“标准—证据—结论”映射

1. **模块运行时无旧 seal、模块级 32-byte key、命名为 mint/signer/factory 的 callable**：现有 R2 测试通过，运行时 namespace 中也没有 `_FORMAL_FACTS_SEAL` 或 `_initialize_formal_facts_capability`。**字面 surface 检查通过，但未形成来源闭包**；公开 loader 的 `__closure__` 直接含 `mint` callable，见 P1。
2. **单一初始化 closure、public constructor 拒绝、registry 按实例身份**：源码显示 constructor 稳定拒绝，空 `object.__new__`、完整 slots clone 和未登记 clone 被现有测试拒绝。**局部通过**；但 registry 与签发函数均可经公开函数 closure 反射取得，caller 可直接调用真实 `mint` 并被 registry 登记。
3. **identity、八帧内容、whole-hash、provenance、nonce、attestation 绑定**：源码会对八帧重算 schema、物理顺序、全内容 hash 与 whole-hash，再以 HMAC 绑定 provenance/nonce；13 个签发 slots 漂移、伪 whole-hash、八帧重签均被现有测试拒绝。**对已签发实例的篡改检测通过，但签发来源不通过**。
4. **每个 public property、identity、repr 消费前统一验证，DataFrame 返回 clone**：现有测试覆盖 identity、八个 property 与 repr，合法 property 返回 clone，attestation 漂移后均 fail closed。**通过现有覆盖**。
5. **稳定脱敏错误与不可 pickle**：constructor、伪造、漂移、hostile upstream 与 pickle 均得到 `M3_A_SHARE_MARKET_FACTS_INVALID`；已检查路径的 cause/context 为空，repr 不含 attestation、nonce、key、registry 或 provenance。**通过现有覆盖**。
6. **reload 后旧 capability 拒绝**：孤立运行时通过。**测试隔离不通过**；该用例 reload 模块后不恢复原模块身份，随后 development facts exact-type 回归稳定失败，见 P2。
7. **R1 八表窗口、FULL_DAY/reconciliation、生命周期、limit、benchmark、fresh 顺序与物理顺序回归**：formal facts 文件的 R1 用例在双平台随 22 项 R2 定向测试通过；源码中的 selector 与 stable-read 路径仍在。**既有定向覆盖通过**。same-bytes root/file replacement 的 R1 独立证据未被本轮生产改动删除，但它不能弥补当前 P1 签发绕过。

## 3. P1 阻断：公开 loader 反射暴露真实签发函数

### 现象

`load_verified_a_share_market_facts` 是普通 Python closure。其公开反射接口直接暴露 free variable：

```python
f = facts_module.load_verified_a_share_market_facts
closure = dict(zip(
    f.__code__.co_freevars,
    (cell.cell_contents for cell in f.__closure__),
    strict=True,
))
assert callable(closure["mint"])
```

独立内存反例随后把 caller 自造的 portable identity、八个合法 shape DataFrame 与任意 `_PathEntity` provenance 直接传给该 `mint`，完全没有调用 public loader、`verify_g1_release` 或 `verify_backtest_plan_artifact`。实际输出：

```text
MINT_EXPOSED True
EXACT_TYPE True
CALLER_HASH_ACCEPTED ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
PUBLIC_CONSUMER_ACCEPTED 113 VerifiedAShareMarketFacts(input_market_facts_sha256='ffffffff...')
```

伪造对象不仅是当前 module 的 exact `VerifiedAShareMarketFacts`，还被真实 issued registry 登记、由真实 HMAC key 签名，并通过 `identity`、`bars` 和 `repr` 的统一 verifier。

### 根因

R2 把“模块 attribute 不可见”等同于“caller 不可取得”。Python closure cell 可通过函数的 `__closure__` 和 `__code__.co_freevars` 公开反射；`public_loader` 在 `src/quant/backtest/a_share_execution.py` 的返回路径直接捕获 `mint`。因此 `_FORMAL_FACTS_SEAL` 虽被删除，R1 的 generic signer surface 实质上只是从模块 namespace 移到了公开函数 closure。

进一步说，只要威胁模型允许 caller 使用本任务已经明确采用的 `object.__new__`、`object.__setattr__` 等 Python 反射能力，就不能把普通 Python closure 当作不可观察的安全边界。即使从 loader closure 去掉 `mint`，property getter 的 closure 仍可继续通向 verifier、registry 或 signing key，除非重新冻结威胁模型或改变信任边界。

### 违反的规则与系统不变量

- 任务单第 7、11 节：“capability 只能由 loader 在最后一步签发”“mint、verify、issued registry 只存在 closure 内”的目的性约束。
- G1/G7B fresh 来源闭包：任何可消费 exact formal capability 必须在 fresh G1 与 fresh G7B 成功、八表 stable read/数学闭包完成后才签发。
- R1 的通用教训：“仅改变可见性或 underscore 命名不能形成 capability 边界”。

### 最小复现与新增测试

新增回归不应只扫描 `vars(module)`；至少应从以下所有公开入口递归检查 closure/reflection 可达对象，并证明不能取得 callable signer、registry 或 signing material：

1. `load_verified_a_share_market_facts.__closure__`；
2. `VerifiedAShareMarketFacts` 的 property `fget`、`__repr__`、`__reduce__` 的 closure；
3. 通过取得的任一 callable 或 registry，尝试用 caller identity、八帧和 provenance 签发并由每个 public consumer 接受。

本轮上述第 1、3 项已构成最小失败复现。

### 通过条件

主 Agent 应先重新冻结威胁模型与可实现边界，不能要求实现者继续把普通 Python closure 当作不可反射的私密区。至少需要二选一：

- 明确排除同进程 Python 反射/monkeypatch 能力，并相应降低“不可伪造 capability”的安全表述；或
- 把签发秘密与 registry 移出 caller 可反射的 Python 对象图（例如受控 native/隔离进程边界），并由独立测试证明 public Python surface 无法取得签发能力。

在重新冻结后，caller 必须无法绕过 fresh loader 获得 registry 登记且所有 public consumer 可接受的 exact formal capability。

## 4. P2：reload 测试污染后续邻接回归

### 现象与最小复现

按以下顺序运行两个测试节点，Windows 与 WSL base 均稳定得到 `1 passed, 1 failed`：

```text
test_m3_formal_a_share_market_facts.py::test_r2_reload_rejects_old_capability
test_m3_a_share_market_facts.py::test_market_facts_builder_binds_exact_eight_release_files
```

失败断言为：

```text
type(facts.identity) is AShareMarketFactsIdentityV1
```

两侧显示相同限定名，但不是同一 class identity。

### 根因、规则与通过条件

reload 用例调用 `importlib.reload(facts_module)` 后未恢复进程级模块状态；其他测试在 collection 阶段导入的 class 与 reload 后 builder 使用的新 class 分裂。它违反测试隔离与任务单第 10/11 节要求保留 development facts 邻接回归的约束。

新增测试或修复必须保证 reload 用例结束后恢复模块及相关导出身份，或将 reload 探针隔离到子进程。通过条件是上述两节点按当前顺序和 formal/G7B/development/G7E 邻接集合在 Windows、WSL base 均通过。

## 5. 实际验证结果

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- formal facts：**22 passed，7319 warnings，21.61s**。
- 定向 Ruff（三个白名单文件）：**All checks passed**。
- 定向 mypy（两个生产文件）：**Success: no issues found in 2 source files**。
- reload + development 最小邻接复现：**1 passed, 1 failed，2534 warnings，30.34s**。
- closure 新反例：**成功绕过 public loader 并签发可消费 exact formal capability**。

WSL Miniforge base，`/mnt/f/.../m3-g4-formal`：

- formal facts：**22 passed，7319 warnings，18.76s**。
- 定向 Ruff（三个白名单文件）：**All checks passed**。
- 定向 mypy（两个生产文件）：**Success: no issues found in 2 source files**。
- formal facts + G7B + development facts + G7E 邻接集合：**45 passed, 1 failed，22993 warnings，95.57s**；失败即 reload 后的 development exact-type 身份分裂。
- reload + development 最小邻接复现：**1 passed, 1 failed，2534 warnings，17.22s**。
- `findmnt`：`/mnt/f F:\ drvfs ...`，明确不是 ext4。

warnings 均为既有 Pandera Polars `concat(how='horizontal')` deprecation；未见本轮新增代码诊断。测试与静态检查绿色只能证明已编码样例和静态质量，不能覆盖已实证的 P1 来源绕过。

## 6. 最终结论

G7D-F0 R2 **FAIL，返回主 Agent 重新冻结边界后返工**。当前不得进入主 Agent 最终通过、不得把本任务或 G7/M3/Linux ext4 Gate 标为通过，也不得据此解锁 G7C formal 返工。

本轮未修改生产代码或测试；除本报告外无范围内写入。核心剩余风险不是 hash/HMAC 算法本身，而是把同进程可反射的 Python closure 错当作不可取得的签发边界。
