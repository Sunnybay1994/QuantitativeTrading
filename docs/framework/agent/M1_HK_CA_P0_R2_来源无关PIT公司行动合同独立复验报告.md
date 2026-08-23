# M1-HK-CA-P0 R2 来源无关 PIT 公司行动合同独立复验报告

日期：2026-08-09（Asia/Shanghai）  
角色：未参与 R2 实现的全新独立初验 Agent  
结论：**FAIL**

## 1. 范围与边界

只读检查了 `AGENTS.md`、`.ai` 通用规则、P0 任务单 §15、R1 FAIL 报告、R2 交付报告、生产实现、schema、公共导出与实现者测试。除本报告外未修改生产代码或测试；未联网、未调用 connector/SDK、未读取 token、未扫描或写入正式 `data/`、HK60/U0C/G1 journal、候选或发布目录，也未 add/commit。

R2 已关闭 R1 的两个原始缺陷：消费者会逐 raw file fresh 重算 content/metadata digest；adapter、projection factory、selector 和 result verifier 会在离开 active `except` 后重建稳定错误。因此旧摘要篡改和异常链 marker 的常规反例均已通过。然而，新增 whole-rehash 反例仍可保留旧 verified seal 并把任意新 retained bytes 伪装为既有 adapter 已验证 projection，击穿本包最核心的“verified projection 绑定实际被 adapter 解释的 retained bytes”不变量。

## 2. 阻断问题 F1：whole-rehash 可复用旧 seal 绕过 adapter 验证

### 现象

对一个已由 fixture adapter 验证的合法 projection 做以下低层篡改：

1. 把 raw `content` 改为与原候选完全不一致的 `b'{"records":[]}'`；
2. fresh 重算该 raw 的 `content_sha256`；
3. fresh 重算 bundle SHA；
4. 把 candidates 的 `raw_file_sha256`、`raw_bundle_sha256`、predecessor/candidate identity 全部按新值重算；
5. fresh 重算 projection SHA，但原样保留旧 `_seal`；
6. 调用公开 `select_hk_corporate_actions`。

实际输出：`WHOLE_REHASH_ACCEPTED 3 6`。selector 接受了声称 raw 为“零 records”但仍携带三条 canonical action、六条 revision evidence 的 projection。

### 根因

- `VerifiedHkCorporateActionProjection` 的 seal 只是所有实例共享的全局 `_SEAL` 身份检查（`src/quant/data/hk_corporate_actions.py:255-276`），不绑定 adapter 当时验证的 raw/bundle/candidate/projection 摘要。
- `_verify_projection`（`src/quant/data/hk_corporate_actions.py:472-495`）会重算当前对象内彼此自洽的各层 hash，却没有可信根证明“这些候选确实来自 adapter 对这些 retained bytes 的解析”。
- `_candidate_id` 与 `_projection_sha256`（`src/quant/data/hk_corporate_actions.py:723-729,827-834`）均可由已篡改的公开字段重新推导；所以 whole-rehash 后形成新的自洽闭环，但不是原 adapter 已验证的闭环。

这不是 SHA-256 碰撞问题，而是 verified capability 的 attestation 未绑定其内容。R2 对 stale digest 的修复有效，但仅靠可重算的公开摘要不能区分“adapter 验证结果”和“调用方重签的自洽对象”。

### 违反规则

- P0 §5.1：selector 必须 fresh 重验全部闭包，不能因为 verified 类型名而信任内容；调用方不能自报 verified projection。
- P0 §14：retained raw/metadata/bundle/projection 必须 fresh digest 闭包。
- P0 §15：R2 后 projection/selection 消费前必须闭包实际 retained bytes，低层篡改应 fail closed。

### 最小返工规则

1. projection 的不可伪装 seal 必须绑定 adapter factory 当时验证的 capability/query/raw files/bundle/candidates/projection identity，消费者 fresh 重验时必须同时核对该绑定；不能继续使用不携带内容身份的全局 sentinel。
2. 不改变公开 schema、event/candidate/query/bundle/projection identity 算法、revision/PIT 语义、Protocol 或稳定错误码。
3. whole-rehash 失败仍映射 `HK_CA_EVIDENCE_INVALID`，`cause/context` 均为空，traceback 不包含 raw marker。
4. 新增回归必须从合法 verified projection 出发，修改 raw bytes并重算 raw、bundle、candidate chain 与 projection 全部公开摘要；保留旧 verified attestation 时 selector、result verifier 均须拒绝。不能只测“改 bytes、保留旧 digest”的 stale-hash 情形。

通过条件：上述 `b'{"records":[]}'` 反例在 Windows 与 WSL base 均稳定拒绝；既有 raw stale-digest、revision、future withdrawal/tombstone、result 重签及异常链矩阵保持绿色，再由另一全新独立 Agent 复验。

## 3. 其余独立反例结果

| 反例 | 结果 | 证据 |
|---|---:|---|
| 分别篡改 raw content、metadata、content digest、metadata digest；selector/result verifier | PASS | `STALE_RAW_BOUNDARIES_PASS 8 /8`，均为干净的 `HK_CA_EVIDENCE_INVALID` |
| 同 bytes 的两个独立 raw 对象、重复对象、逆 canonical 次序、role 变化 | PASS | 同 role/同 digest 重复拒绝；逆序拒绝；role 改变 bundle identity |
| factory/selector/result verifier 在 ValueError/RuntimeError active context 中抛全部六个稳定码 | PASS | `PUBLIC_BOUNDARY_STABLE_ERROR_MATRIX 36 /36`；固定 code，cause/context 为空，traceback 无 marker |
| hostile adapter 的稳定/未知异常 | PASS | 实现者矩阵覆盖 18 个稳定组合及未知异常映射；定向套件绿色 |
| future WITHDRAWN 被重签为 selected tombstone | PASS | verifier fresh rebuild 后 `HK_CA_RESULT_INVALID` |
| 已撤回事件被伪造成 canonical action并重算 result hash | PASS | verifier fresh rebuild 后 `HK_CA_RESULT_INVALID` |
| no-lookahead、withdrawal/tombstone、revision chain、schema 回归 | PASS | 双平台定向套件 90 passed |

## 4. 实际验证

Windows 原生 Miniforge：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py -q -p no:cacheprovider --basetemp artifacts/test-tmp/hk-ca-p0-r2-independent-win
90 passed, 4345 warnings in 12.86s

D:\Miniforge3\python.exe -m ruff check src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py
All checks passed!

D:\Miniforge3\python.exe -m mypy src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py
Success: no issues found in 3 source files
```

WSL Miniforge `base`，同一 worktree 的 `/mnt/f` 路径：

```text
python -m pytest ...
90 passed, 4345 warnings in 12.29s

python -m ruff check ...
All checks passed!

python -m mypy ...
Success: no issues found in 3 source files
```

该 WSL 路径是 DrvFS；上述结果只证明 Windows/WSL 跨平台开发反馈，不是 ext4 Gate。

## 5. 结论

**R2 独立复验 FAIL。** R1 的 stale raw digest 和异常链泄漏已修复，常规定向测试与静态检查均绿色；但 whole-rehash 能复用旧全局 seal，在不重新调用 adapter 的情况下把新 raw bytes 与旧候选语义重新签成可被 selector 接受的 verified projection。P0 开发合同暂不关闭，也不构成真实 HK 来源、HK60、复权/total-return、M1 或 Linux/ext4 Gate 通过。
