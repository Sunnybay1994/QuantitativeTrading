# M1-HK-CA-P1-PRE-B R2：目录锚与异常图脱敏独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的全新独立复验 Agent  
结论：**FAIL；不得进入主 Agent 终验或正式 v3 migration**

## 1. 复验边界

本轮完整阅读了项目 `AGENTS.md`、`.ai/README.md`、Availability Receipt v3 任务单 §11、R1 FAIL
报告和 R2 返工交付报告；只读核对生产代码与实现者测试。没有联网，没有读取或写入正式 02983/01065
data、journal 或候选目录，没有 add/commit。唯一 worktree 写入是本报告；独立探针只使用系统临时目录中的
synthetic fixture。

## 2. 已确认通过的 R2 项

1. journal、seed、raw-store、clean 四类 root 均在 public load/verify 的 fresh rebuild 中建立
   `_ReadAnchors`；POSIX 文件读取使用 root dir-fd 逐级 `open(..., dir_fd=..., O_NOFOLLOW)`，Windows 根目录
   handle 不共享 delete，后代与文件读取拒绝 reparse。
2. 实现者新增的四 root × load/verify 窗口内 original→copy ABA 测试在 Windows 和 WSL/DrvFS 均通过；
   Windows 的 root rename 被 no-share-delete handle 阻止，POSIX namespace 替换稳定 fail closed。
3. 独立 hostile matrix 对 JSON、Parquet、HKEX verifier、root reader 分别注入 `ValueError` 与
   `RuntimeError`。public loader 的最终异常 `cause/context` 均为 `None`，递归异常图、`repr` 和格式化
   traceback 均无 marker。实现者的 load/verify 双边界矩阵和 HKEX retained public verifier 回归也通过。
4. legacy v1/v2 unsupported、v3 whole-rehash 后旧 capability 拒绝、四文件事务 rollback/no-clobber、
   symlink/reparse 与 source closure 回归均包含在定向全组并保持绿色。

这些结果关闭了 R1 的原始 root-path ABA 与 hostile exception graph 问题，但第 3 节的新反例仍违反任务单
§11.2 的明文不变量。

## 3. 阻塞问题

### 3.1 [P1] 锚 handle/fd 在 capability 签发前漂移仍会被接受

**现象**

独立探针捕获本次 `_ReadAnchors`，在所有 source/clean 读取完成、`_capability_attestation` 计算前调用
`anchors.close()`，随后让原 attestation 逻辑继续。Windows 与 WSL/DrvFS 均成功返回
`VerifiedHkBarBundle`：

```text
Windows: HANDLE_CLOSE_ACCEPTED
WSL:    HANDLE_CLOSE_ACCEPTED
```

该反例没有替换任何数据，也没有伪造 capability；它只使本应贯穿到签发完成的物理锚提前失效。

**根因**

`src/quant/data/hk_history_backfill.py:1776` 的 `_DirectoryAnchor.close()` 将 `_fd`/`_handle` 置为 `None`，
但 `assert_namespace()`（约 1784 行）不先证明原锚仍开放：Windows 重新打开 path 取 identity，POSIX 直接调用
path-based `_root_identity()`。`_ReadAnchors.assert_namespaces()`（约 1828 行）因此只能证明当前 namespace
仍指向同一 identity，不能证明本验证窗口的原 handle/fd 仍存活。

`load_verified_hk_bar_bundle` 在 2293 行第一次 namespace check 后构造 capability，并在 2303 行计算
attestation；即使四个锚就在该阶段全部关闭，2311 行的第二次 path-based check 仍通过，finally 中再次
`close()` 也只是 no-op，最终签发 capability。

**被破坏的不变量**

任务单 §11.2 明确要求四类权威 root 的目录锚“保持到全部 source rebuild、schema/identity 比对和 capability
签发完成”，并规定“handle/fd 漂移 fail closed”。当前实现只验证路径身份，不验证活锚生命周期，因此这一
高风险 physical-root freshness 合同尚未成立。

**最小复现**

1. 用 `_published_v3` 在系统临时目录生成 synthetic v3；
2. 包装 `_ReadAnchors.__init__` 捕获本次 anchors；
3. 包装 `_capability_attestation`，先执行 `captured_anchors.close()`，再调用原函数；
4. 调用 `load_verified_hk_bar_bundle`；当前 Windows/WSL 结果均为成功返回。

**新增测试要求**

- load 与 verify 两个 public 边界均覆盖：在最后一次文件读取后、attestation/最终 namespace check/返回前，
  分别关闭 journal、seed、raw、clean 的单个锚及整组锚；必须稳定返回 `HK_BAR_VERIFY_FAILED`；
- `assert_namespace()` 必须首先验证本锚仍持有有效且 identity 不漂移的原 handle/fd，不能通过重新打开 path
  代替原锚存活证明；关闭后调用必须 fail closed；
- Windows 检查 handle validity 与 handle identity，POSIX 检查 fd validity 与 `fstat(fd)` identity；最终
  namespace→anchor 对照仍应保留；close 应维持幂等，且 close failure 继续由 public 边界脱敏；
- 补一个后代目录或 exact 单文件在读取窗口中替换的对抗测试，明确区分“仍由活 root 锚相对打开且内容摘要
  拒绝”与“锚已失效后退化为 path reopen”。

**通过条件**

上述 handle/fd close/drift 矩阵在 Windows 与 WSL base 均 fail closed，R1/R2 全组继续绿色，生产外部
schema、availability retained-observation 语义、legacy v1/v2 和四文件发布格式保持不变。

## 4. 验证结果

### Windows 原生 Miniforge

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
  tests/unit/test_hk_history_backfill.py -q
134 passed, 1 skipped

ruff（7 个定向 source/test 文件）: All checks passed!
mypy（4 个 source 文件）: Success: no issues found in 4 source files
独立 exception graph matrix: EXCEPTION_GRAPH_MATRIX_PASS 8
独立 handle-close probe: HANDLE_CLOSE_ACCEPTED
```

skip 是既有 official retained raw 条件，不影响 synthetic v3 合同矩阵。

### WSL Miniforge base

```text
同组三文件 pytest: 135 passed
ruff: All checks passed!
mypy: Success: no issues found in 4 source files
独立 handle-close probe: HANDLE_CLOSE_ACCEPTED
```

当前工作树实际位于 `/mnt/f` DrvFS；这些结果只属于双平台开发合同反馈，不是 ext4/Linux Gate。

### 范围与格式检查

- `git diff --check` 通过，仅有既有 LF/CRLF 提示；
- 保留了 worktree 中全部既有无关脏文件；
- 未修改生产代码、实现者测试或正式数据。

## 5. 裁定与边界

R2 已实质修复 R1 的两项原始漏洞，但新的 handle/fd 生命周期反例直接违反同一冻结条款，因此独立复验仍为
**FAIL**。建议仅返工活锚状态/identity 检查与对应测试，不改变 v3 外部格式或业务语义；返工后由另一个全新
独立上下文复验。

即使后续复验通过，本包仍只证明开发态 availability/bar capability 合同；正式 v3 migration、真实 HK 公司
行动、01065/HK60、ext4 与 M1 Gate 均未通过。
