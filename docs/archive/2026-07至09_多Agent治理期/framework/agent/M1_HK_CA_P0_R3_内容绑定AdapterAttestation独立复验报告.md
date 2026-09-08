# M1-HK-CA-P0 R3 内容绑定 Adapter Attestation 独立复验报告

日期：2026-08-09（Asia/Shanghai）  
角色：未参与 R3 实现的全新独立初验 Agent  
结论：**PASS（仅关闭 HK-CA-P0 来源无关开发合同；不代表任何正式 Gate）**

## 1. 范围与独立性

完整核对了根 `AGENTS.md`、`.ai` 工程规则、P0 任务单 §16、R2 FAIL 报告、R3 交付报告、
`src/quant/data/hk_corporate_actions.py`、对应 schema/公共导出及实现测试。生产代码和实现测试全程只读；
除本报告外未修改交付文件，未 add/commit，未联网、未调用 HK 数据源/SDK，未读取凭据，也未触碰 HK60、
U0C、G1 journal、正式候选或发布目录。

R3 的关键不变量是：adapter-facing factory 只能生成 `adapter_parsed` 对象；只有 source wrapper 对 retained
bytes、query、bundle、candidate 和 projection 全闭包 fresh exact 重验后，才能签发内容绑定、进程本地的
`source_verified` capability。selector 与 result verifier 每次都必须重验公开闭包及 HMAC，不能接受
factory-only 对象或把旧 token 移植到另一组自洽内容。

## 2. R2 失败闭环复核

| 验收项 | 独立证据 | 结论 |
|---|---|---:|
| factory-only projection 拒绝 | 从合法 source-verified projection 重新经公开 factory 构造 parsed-only 对象；selector 与 result verifier 均返回干净 `HK_CA_EVIDENCE_INVALID` | PASS |
| source wrapper 正常签发 | 合法 fixture adapter 经 wrapper 后可选择 3 条 action，并由 result verifier fresh 重建通过 | PASS |
| R2 whole-rehash + 旧 token | 定向套件覆盖 raw content/metadata/source issue/candidate/projection digest 重哈希后复用旧 attestation，selector 与 result verifier 全部拒绝 | PASS |
| 跨另一合法对象复用旧 token | 独立新增一次性反例：把同一旧 token 分别移植到另一合法 query、adapter version、candidate set 和 source 的 projection，`CROSS_LEGAL_TOKEN_SWAP_REJECTED 4` | PASS |
| factory 结果重放给 wrapper | 已签发 projection 不能冒充 adapter-parsed 返回值；wrapper 拒绝带 attestation 的 replay | PASS |

实现先用 `_verify_projection_contents` fresh 重算 retained bytes 的 content/metadata digest、bundle identity、
candidate table 与 projection identity，再用模块进程内随机 key 对冻结的六项 payload 重新计算 HMAC，并以
`hmac.compare_digest` 比对。R2 中“公开摘要全链可重算但旧全局 seal 仍可复用”的缺口已关闭；跨合法对象
置换也未形成旁路。

## 3. 生命周期、脱敏与 PIT 回归

| 反例 | 结果 |
|---|---:|
| attestation 不进入 projection repr/dataclass compare，token repr 不暴露 digest，key 不在 `__all__` | PASS |
| projection 与 attestation 均拒绝 pickle；模块 reload 后旧 projection 失效，重新 source verification 后恢复 | PASS |
| source signing、selector compare、result verifier compare 的 hostile HMAC 异常 | PASS：固定 `HK_CA_EVIDENCE_INVALID`，cause/context 均为空，traceback 不含 marker |
| hostile adapter 的稳定/未知异常矩阵 | PASS：稳定码重建，未知异常脱敏映射 |
| future withdrawal、最终 tombstone、no-lookahead、revision chain、whole-result fresh verifier | PASS |
| raw content/metadata 的 stale digest 与全链 fresh digest | PASS |

独立一次性反例另行得到：

```text
CROSS_LEGAL_TOKEN_SWAP_REJECTED 4
REDACTION_LIFECYCLE_PASS
SOURCE_VERIFIED_FACTORY_BOUNDARY_PASS
HOSTILE_HMAC_REDACTION_PASS
```

该机制的可信边界与任务单一致：它防止普通调用方把已签发 capability 替换到另一组公开自洽内容；它不是
外部数据源数字签名、跨进程证书、WORM，也不声称抵抗可任意调用模块私有实现的恶意同进程代码。

## 4. 实际验证

Windows 原生 Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py \
  -q -p no:cacheprovider --basetemp .pytest-hkca-p0-r3-independent-win
102 passed, 6267 warnings in 18.67s

D:\Miniforge3\python.exe -m ruff check \
  src/quant/domain/schemas.py src/quant/domain/__init__.py \
  src/quant/data/hk_corporate_actions.py \
  tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py
All checks passed!

PYTHONPATH=src D:\Miniforge3\python.exe -m mypy \
  src/quant/domain/schemas.py src/quant/domain/__init__.py \
  src/quant/data/hk_corporate_actions.py
Success: no issues found in 3 source files
```

WSL Miniforge `base`，同一 worktree 的 `/mnt/f` 路径：

```text
PYTHONPATH=src python -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py \
  -q -p no:cacheprovider --basetemp .pytest-hkca-p0-r3-independent-wsl
102 passed, 6267 warnings in 16.99s

python -m ruff check ...
All checks passed!

PYTHONPATH=src python -m mypy ...
Success: no issues found in 3 source files
```

警告均为既有 Pandera/Polars deprecation warnings。WSL 路径是 WSL1 DrvFS `/mnt/f`，不是 ext4；该结果只
证明 Windows/WSL 双平台开发反馈，不构成 Linux/ext4 Gate。

## 5. 结论与剩余边界

**R3 独立复验 PASS。** R2 的 content-unbound seal 缺陷已按 §16 关闭，factory/source 两阶段能力、内容绑定
HMAC、fresh retained-byte 闭包、失败脱敏、进程生命周期和 PIT/withdrawal/result 回归均有实际证据。
HK-CA-P0 来源无关开发合同可以进入主 Agent 最终验收。

仍未验证且不得随本结论关闭：真实 HK 来源格式、许可与 revision/withdrawal completeness、HK60、港股复权/
total-return、M1 正式 Gate、Linux/ext4 Gate。进程重启后仍必须重新调用 source wrapper 对 retained bytes 做
fresh verification。
