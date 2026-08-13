# M1-HK-CA-P0 R3 内容绑定 Adapter Attestation — 返工交付报告

日期：2026-08-09（Asia/Shanghai）  
状态：**R3 已交付，待全新独立上下文复验；不自行宣布 P0 开发合同或任何正式 Gate 通过**

## 1. 结果

- adapter-facing `build_verified_hk_corporate_action_projection` 保持原签名，但只生成
  `adapter_parsed`（无 attestation）projection；selector 与 result verifier 均拒绝直接消费。
- `verify_hk_corporate_action_source` 仍先做 capability/query/bundle preflight，再调用 adapter，fresh exact
  重验 projection 全闭包；只有该路径成功后才创建新的 `source_verified` projection，并签发进程本地
  HMAC-SHA256 attestation。
- attestation payload 精确绑定 source、adapter version、query identity、bundle identity、candidate table digest
  与 projection digest。selector/result verifier 每次先 fresh 重验 retained bytes、公开摘要与候选语义，再重新
  计算 HMAC 并用 constant-time comparison 核对。
- projection 和 attestation 均显式禁止 pickle；attestation 不进入 dataclass repr/equality，进程密钥不导出、
  不进入 `__all__`、日志、artifact 或文档。模块重载会产生新进程内密钥，旧 projection 随即 fail closed，必须
  再次调用 source wrapper 对 retained bytes fresh verification。
- R2 的逐 raw file fresh content/metadata digest 与稳定脱敏异常重建保持不变；未改变 Schema、公开 Protocol、
  identity/revision/as-of/selection 语义或稳定错误码。

## 2. R2 失败闭环

| 现象 / 规则 | R3 实现 | 新增证据 |
|---|---|---|
| whole-rehash 可复用全局 `_SEAL` | `_SEAL` 只保留私有构造边界；source-verified 能力额外要求内容绑定 HMAC | raw content 改成 `{"records":[]}` 后，重算 raw、bundle、candidate chain、projection 全部公开摘要并保留旧 token，selector/result verifier 均稳定拒绝 |
| factory 自报 verified | factory 产物 attestation 固定为空；source wrapper 只接受 parsed-only adapter 返回 | factory-only 直接消费失败；把已签发 projection 从 adapter 重放给 source wrapper 也失败 |
| 旧 token 可能跨内容复用 | HMAC payload 显式绑定六项身份，消费者 fresh 重算并 constant-time compare | content、metadata、source issue、candidate row、projection digest 五类旧 token 复用均失败 |
| token/key 泄漏或跨进程误用 | 私有随机 key；token repr/equality 排除；projection/token 不可 pickle | repr/pickle/公共导出测试；模块 reload 后旧 capability 失效、fresh source verification 后恢复 |
| hostile HMAC 异常链泄漏 | 继续采用“捕获 code → 离开 active except → 新建稳定错误”边界 | source signing、selector compare、result verifier compare 三条 hostile HMAC 路径均为干净 `HK_CA_EVIDENCE_INVALID`，traceback 无 marker |

## 3. 修改范围

- `src/quant/data/hk_corporate_actions.py`：parsed/source-verified 两阶段能力、进程本地内容绑定 attestation、
  fresh constant-time verification 与不可序列化边界。
- `tests/unit/test_hk_corporate_actions.py`：新增 12 项 R3 对抗/生命周期测试；既有 R2、PIT、withdrawal、
  tombstone、revision、whole-result 与异常矩阵继续执行。
- 本报告。

未修改 connector、HK60、U0C、G1、正式数据、journal、候选或发布目录；未联网、未读取 token、未安装依赖，
未 add/commit。worktree 中任务开始前已有的 HK history/HKEX/HK60/U0C 代码、文档与临时 pytest 目录均保留，
不认领也不清理。

## 4. 实际验证

Windows 原生 Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py -q -p no:cacheprovider --basetemp artifacts/test-tmp/hk-ca-p0-r3-final2-win
102 passed, 6267 warnings in 24.13s

D:\Miniforge3\python.exe -m ruff check src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py
All checks passed!

D:\Miniforge3\python.exe -m mypy src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py
Success: no issues found in 3 source files
```

WSL Miniforge `base`，同一 worktree 的 `/mnt/f` 路径：

```text
PYTHONPATH=src python -m pytest ...
102 passed, 6267 warnings in 18.80s

python -m ruff check ...
All checks passed!

python -m mypy ...
Success: no issues found in 3 source files
```

WSL 路径是 DrvFS，不是 ext4；上述结果只证明双平台开发合同反馈，不构成 Linux/ext4 Gate。

## 5. 设计边界与仍待事项

- HMAC attestation 只防止普通调用方把已签发能力替换到另一组公开自洽内容；它不是外部数据源数字签名、
  跨进程证书、WORM 或对任意恶意同进程代码的隔离边界。
- projection 是进程内 capability，重启/模块重载后必须再次经 source wrapper fresh verification；不提供持久化。
- 真实 HK 来源格式、许可、revision/withdrawal completeness、复权/total-return、HK60、M1 与 ext4 Gate 仍未验证。
- 下一步必须由未参与 R3 实现的全新独立 Agent 复验任务单 §16、whole-rehash、factory-only、旧 token
  复用、hostile HMAC 与进程生命周期边界，再由主 Agent 裁定。
