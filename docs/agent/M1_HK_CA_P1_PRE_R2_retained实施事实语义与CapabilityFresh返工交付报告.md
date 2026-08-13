# M1-HK-CA-P1-PRE R2：retained 实施事实语义与 Capability Fresh 返工交付报告

日期：2026-08-09  
状态：**R2 已交付，待全新独立上下文复验；不自行宣布开发合同或任何 Gate 通过**

## 1. 返工结论

本轮只修复独立初验的两个阻断，没有实现 HK bar capability，也没有修改 HK history：

1. 正向 fixture adapter 现在 strict 解析 canonical retained implementation JSON records。每条 record 的
   event/revision/source、`implementation_status`、effective date、confirmed/observed time 和 source record id
   都来自 retained bytes；P0 actions 只用于 exact event/revision/source 对账，不再被用于合成
   `IMPLEMENTED`、确认时间或实施日期。
2. `HkCorporateActionImplementationCapability` 增加不进入 repr/equality 的进程内构造 attestation，绑定
   source、adapter version 和全部 required booleans。`_preflight` 在 factory、source wrapper、selector 和
   public set verifier 的每次 fresh 消费中同时重验严格类型、trim 后非空、全部布尔值及构造 attestation；
   低层修改为另一非空 source/version 也不能重新获得签发。

R1 的 projection/set content-bound HMAC、whole-rehash 旧 token 拒绝、factory-only、pickle、exact P0 绑定与
异常脱敏保持。

## 2. FAIL 闭环

### 2.1 ACTIVE/日期冒充 IMPLEMENTED

- 现象：R1 fixture raw 只有 `scope_complete`，adapter 遍历 P0 ACTIVE actions 后自行填写实施事实。
- 根因：fixture adapter 没有演示真实信任边界“retained implementation record → parsed evidence”。
- R2 规则：top-level 和 record 字段集合 exact；JSON duplicate key、unknown field、truncation、scope/correction/
  withdrawal completeness 非 true、record 缺失/重复均 fail closed。status 只接受 retained `IMPLEMENTED`；
  confirmed time 必须直接解析自 retained record。
- 新增复现：only-scope + P0 全 ACTIVE/除权日已过、PENDING/ANNOUNCED/APPROVED/COMPLETED_BY_DATE、future
  confirmation、缺 status/confirmation/source record/revision、unknown/duplicate/truncated raw 全部拒绝。
- withdrawal：retained future withdrawal 不改写较早 as-of；withdrawal 在当前 as-of 已确认时拒绝继续输出
  implemented set。

### 2.2 Capability 构造不变量只验一次

- 现象：合法 capability 构造后低层把 `adapter_version` 改为空，wrapper 仍签新 token。
- 根因：R1 `_preflight` 只检查 required booleans 为 true。
- R2 规则：构造时用进程内密钥为 source/version/全部 booleans 签 content-bound attestation；每个 fresh
  consumer 先重算并 constant-time 比对，再进入 adapter 或 projection HMAC。
- 新增复现：source 与 adapter version 分别低层改成空串、空白、整数、另一合法非空值，factory、source
  wrapper、selector、public set verifier 四个边界均返回
  `HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED`；source wrapper 在 preflight 失败时不调用 adapter。

## 3. 修改范围

- `src/quant/data/hk_corporate_action_implementation.py`：capability construction attestation 与完整 fresh
  preflight。
- `tests/unit/test_hk_corporate_action_implementation.py`：strict retained fixture parser、canonical records、
  status/confirmation/withdrawal/scope 反例和 source/version 四边界低层篡改矩阵。
- 本报告。

R1 已有 schema/export/test/report 保持；没有修改 connector、`hk_history_backfill.py`、HK60/U0C/G1、正式
data/artifacts/journal、`data/legacy`、依赖或 enums。未联网、未读取凭据、未 add/commit，既有无关脏文件
原样保留。

## 4. 验证

Windows 原生 Miniforge：

```text
test_hk_corporate_action_implementation.py
39 passed

test_schemas.py + test_hk_corporate_action_implementation.py + test_hk_history_backfill.py
116 passed, 1 skipped in 36.31s

Ruff（改动生产与测试文件）
All checks passed!

mypy（schemas.py、domain/__init__.py、hk_corporate_action_implementation.py）
Success: no issues found in 3 source files
```

WSL Miniforge `base`，同一 `/mnt/f` worktree：

```text
同一三文件 pytest
117 passed in 32.66s

同一文件 Ruff
All checks passed!

同一 3 个生产文件 mypy
Success: no issues found in 3 source files
```

Windows 的一个 skip 是既有平台差异。Pandera/Polars deprecation warnings 未形成断言失败。`/mnt/f` 是
DrvFS，不是 ext4；这些结果只证明双平台开发合同反馈。

## 5. 边界与待验收项

- fixture parser 只解释测试内冻结的 synthetic canonical JSON，不猜测任何真实 HKEX 或供应商格式，也不进入
  production connector。
- capability construction attestation 与 projection/set attestation 都是进程内防替换机制，不是外部数字签名、
  WORM 或跨进程证书。
- HK bar capability 仍按 PRE-B 等待逐 key receipt v3 与 HKEX canonical observed-at 闭包；本轮没有伪造
  `bar_available_at`，也没有触碰 history。
- 真实 licensed implementation source、01065/HK60、gross total-return、M1 与 ext4 Gate 均未验证。
- 下一步必须由未参与 R2 实现的全新独立上下文复验 only-scope、retained status/withdrawal、source/version
  低层篡改和 R1 HMAC/whole-rehash/异常回归，再由主 Agent 裁定。
