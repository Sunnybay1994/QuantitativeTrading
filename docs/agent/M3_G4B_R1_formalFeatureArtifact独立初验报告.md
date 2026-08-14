# M3-G4B-R1 formal FeatureArtifact 独立初验报告

日期：2026-08-02  
角色：未参与实现的独立初验 Agent  
结论：**FAIL，退回实现 Agent 返工**

## 1. 结论摘要

现有实现保持了 development/formal exact capability 类型边界、共享构建/验真逻辑、train-only
schema selection、三 segment coverage/digest 复算、formal worker 的空 processor/label 与父进程 Qlib
隔离。Windows 定向 Ruff、mypy、pytest 均绿色。

但正式 worker 的稳定 identity closure 少了 SSOT 强制的 `provider_uri_sha256`，并且 artifact verifier
会接受 request/response 同时增加的未知字段。两者都破坏 formal request key 与 receipt 所绑定内容的
严格 schema，不满足任务单第 2、3、5 条及 G4B SSOT，故本轮初验失败。仓库当前也没有 formal
build → formal receipt → fresh `verify_feature_artifact` 的成功闭环测试，现有绿色测试不足以证明正式入口可用。

## 2. 合同映射

| 冻结要求 | 证据 | 初验 |
|---|---|---|
| exact formal capability，不接受 development | `build_feature_artifact`、`verify_feature_artifact` 对五类输入均使用 `type(...) is ...`；交叉类型测试存在 | 通过 |
| development/formal 复用内部逻辑 | 两入口共用 `_build_feature_artifact` / `_verify_feature_artifact` | 通过 |
| formal request 无 `example_id`，kind 为 formal | parent 仅在 `example_id is not None` 时写字段；formal worker 使用独立 exact key set | 通过 |
| provider URI 只经环境传递，稳定 identity 绑定 URI 摘要 | URI 仅放入 `M3_QLIB_PROVIDER_URI`，但 request/response 完全缺少 `provider_uri_sha256` | **失败** |
| Qlib 0.9.7 Alpha158、feature-only、空 processors/label | worker 检查 pyqlib 版本，构造 `Alpha158(... infer_processors=[], learn_processors=[], label=([], []))`，只 `prepare(... col_set="feature", DK_I)` | 静态通过；py312 实跑待补 |
| train-only selection、coverage/digest 与 dev 共核 | 共享 `_select_train_schema`、`_publish_segments`、manifest/coverage fresh rebuild | 通过 |
| fresh G4A/upstream/receipt | formal verifier 调用 `verify_fold_plan_artifact`，receipt input/output 使用显式路径和 artifact roots | 静态通过；formal 成功闭环缺证据 |
| exact request/response schema | `_validate_worker_response` 从 request 自身字段推导合法 response 字段，artifact verifier不检查 request exact key set | **失败** |
| 错误脱敏、Windows/WSL | parent 不转发 worker stderr；Windows 定向验证通过；最终 WSL/py312 未执行 | 部分通过 |

## 3. 返工问题一：稳定 identity 缺少 provider URI 摘要

优先级：P1

- 现象：`_EXAMPLE_FEATURE_REQUEST_KEYS`、`_FORMAL_FEATURE_REQUEST_KEYS`、parent request、worker
  response 和 artifact verifier identity 均没有 `provider_uri_sha256`。
- 根因：实现只满足了“不持久化绝对 URI”，遗漏了 SSOT 同一句中的“稳定 request 仅保存
  `provider_uri_sha256`”。provider key/manifest/receipt hash 不能替代本次 worker 初始化 URI identity。
- 应遵循规则：`docs/agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md` G4B 明确要求真实 URI
  只经临时环境传入，而稳定 request/response 必须绑定 `provider_uri_sha256`；formal verifier 必须复算并
  与 fresh verified provider manifest 一致。
- 最小复现：检查已构造 request 的 exact keys；当前集合中不存在 `provider_uri_sha256`，worker response
  也不会 echo 该字段。
- 新增测试：formal 与 development request 都断言只有摘要、没有 URI；篡改摘要后 worker 在 Qlib import
  前拒绝；request/response 摘要漂移和 provider manifest 摘要漂移均由 fresh verifier 拒绝。
- 通过条件：该摘要进入 request exact schema、response echo、artifact verifier identity 和 receipt 输出
  闭包；任何一处漂移均 fail closed，绝对 URI 仍不进入稳定文件。

## 4. 返工问题二：request/response 同增未知字段可绕过 exact schema

优先级：P1

- 现象：`_validate_worker_response` 的 `expected_keys` 由 `set(request)` 动态推导；只要 request 和
  response 同时加入同一个未知字段，校验成功。`_verify_feature_artifact` 只比较已知 identity 字段，未要求
  request key 集合等于 formal/development 冻结集合。
- 根因：response echo 完整性被误当成 request schema 完整性；“两边一致”不等于“字段合法”。
- 应遵循规则：formal/development request 各有独立 exact key set；verifier 必须先按 release kind 校验
  request exact schema，再基于该冻结集合验证 response exact echo。
- 独立对抗反例：直接调用 `_validate_worker_response`，在 request/response 同增
  `injected_unknown="x"`，并提供 158 个唯一 names/expressions。探针 exit 0，输出：

  ```text
  UNKNOWN_REQUEST_RESPONSE_FIELD_ACCEPTED
  ```

  这是实现者现有测试未覆盖的反例。
- 新增测试：在一个合法 development 闭环及一个 formal 闭环中同时修改 canonical request/response，
  重新发布与修改后字节一致的 receipt；fresh verifier 仍必须因 request 未知字段拒绝。另分别覆盖仅 request、
  仅 response 和重复 JSON key。
- 通过条件：上述四类输入全部 fail closed；合法 request/response 的 exact keys 由 release kind 的常量定义，
  verifier不从不可信 request 动态发明 schema。

## 5. 正式闭环证据缺口

任务单要求 formal build → receipt → fresh verify，以及两个 horizon 复用同一 FeatureArtifact。交付报告已如实
说明仓库没有可复用 formal G1→G4A fixture，本轮测试只覆盖 development 成功闭环、formal/development
交叉拒绝和 malformed formal worker request。返工必须增加完整 formal fixture，走公开 formal verifier/receipt，
不得把 development verified dataclass 换壳为 formal。至少断言：

1. 返回 exact `VerifiedFeatureArtifact`；
2. request 为 formal、无 `example_id`、含正确 `provider_uri_sha256`；
3. receipt stage 为 `features`，输入来自各自 artifact root；
4. 两个 horizon 只引用同一 manifest/receipt，不再运行 worker；
5. fresh upstream、request、response、coverage、segment 或 receipt 任一漂移均拒绝。

## 6. 验证结果

Windows 原生 Miniforge，显式使用当前 worktree `src`：

```text
python -m ruff check <3 个生产文件> <3 个定向测试文件>
All checks passed!

python -m mypy src/quant/research/m3/__init__.py \
  src/quant/research/m3/features.py src/quant/research/m3/qlib_adapter.py
Success: no issues found in 3 source files

python -m pytest tests/unit/test_m3_feature_artifact.py \
  tests/unit/test_m3_feature_digests.py \
  tests/unit/test_m3_qlib_worker_protocol.py -q
20 passed
```

pytest 有既有 Pandera deprecation warnings，不影响上述测试结果。

本会话此前启动 WSL 命令时已收到执行额度审查拒绝，并明确要求不要以间接方式重试；因此本轮没有最终
WSL base 或 py312 结果。返工复验必须补跑同组 WSL base Ruff/mypy/pytest，并在 py312 对实际 Qlib 0.9.7
formal worker 做受控 smoke；Windows 绿色不替代 Linux/ext4 Gate。

## 7. 边界与工作区检查

- 未发起网络请求，未触碰正式 G1/G2/G8、journal、provider 或现有 artifact。
- 生产代码和实现测试全程只读。
- 唯一写入为本独立初验报告；未提交。
- 当前结论仅为 G4B-R1 独立初验失败，不对 formal G4/M3 Gate 作通过表述。

---

## 8. R1 返工复验（2026-08-02）

复验角色与首轮相同；生产代码和实现者测试保持只读。R1 结论：**PASS**，可进入主 Agent 最终验收。

### 8.1 首轮三项缺口关闭证据

1. **provider URI 稳定身份已闭合。** formal/development request SSOT 均包含
   `provider_uri_sha256`；构建与 fresh verifier 固定复算
   `SHA256(canonical_json([provider_key, "provider"]))`，worker 在 Qlib import 前复算同一 preimage；response 精确 echo。
   绝对 provider URI 仍只由父进程通过 `M3_QLIB_PROVIDER_URI` 环境变量传入 formal worker，不进入稳定
   request/response/manifest/receipt。
2. **request/response exact schema 已闭合。** `contracts.py` 唯一定义 common、formal、development 与 response extra
   key sets；父进程 `_validate_worker_response()` 与 worker `_parse_feature_request()` 均引用同一 SSOT。验证顺序先检查
   request exact keys，再检查固定 response keys 与逐字段 echo，不再从不可信 request 动态发明 response schema。
3. **formal 公开真链已补齐。** 新测试从 strict formal G1 verifier 开始，依次构造并公开验真 snapshot → provider →
   experiment → fold；随后调用公开 `build_feature_artifact()`，发布 stage=`features` receipt，再由 fresh
   `verify_feature_artifact()` 重验全链。结果类型是 exact `VerifiedFeatureArtifact`，无 `example_id`，两个 horizon 复用同一
   manifest/receipt，worker 调用次数为 1；不是 development verified dataclass 换壳。

### 8.2 独立对抗探针

本轮补充了实现者 formal 闭环未知字段用例之外的 worker 身份攻击。以 exact formal request 为基线：

- 将 `provider_uri_sha256` 改为另一裸 64 位 hex，同时保持其余 identity 自洽；worker 在 Qlib import 前拒绝。
- 恢复正确摘要但向 request 注入绝对路径字段
  `provider_uri="C:\\private\\provider"`；exact formal key schema 在任何 Qlib 操作前拒绝。

```text
FORGED_PROVIDER_URI_IDENTITY_REJECTED feature worker identity invalid
ABSOLUTE_URI_UNKNOWN_FIELD_REJECTED feature worker identity invalid
```

实现者 formal 真链还在 request/response 同时加入 `injected_unknown`、重新发布与漂移后 bytes 一致的 receipt；fresh
public verifier 仍因 exact schema 拒绝，复现并关闭首轮 `UNKNOWN_REQUEST_RESPONSE_FIELD_ACCEPTED` 缺口。

### 8.3 Windows 独立验证

显式使用当前 formal worktree 的 `src`：

```text
D:\Miniforge3\python.exe -m pytest -p no:cacheprovider \
  tests/unit/test_m3_feature_artifact.py \
  tests/unit/test_m3_feature_digests.py \
  tests/unit/test_m3_qlib_worker_protocol.py -q \
  --basetemp=artifacts/g4b-r1-review-protocol2
22 passed, 11152 warnings in 135.79s

D:\Miniforge3\python.exe -m pytest -p no:cacheprovider \
  tests/unit/test_m3_formal_feature_artifact.py -q \
  --basetemp=artifacts/g4b-r1-review-formal
1 passed in 927.86s

D:\Miniforge3\python.exe -m ruff check <3 个生产文件> <4 个定向测试文件>
All checks passed!

D:\Miniforge3\python.exe -m mypy \
  src/quant/research/m3/__init__.py \
  src/quant/research/m3/features.py \
  src/quant/research/m3/qlib_adapter.py
Success: no issues found in 3 source files
```

Pandera warnings为既有 deprecation warning，不影响断言。formal 测试所有写入均位于独立 pytest 临时根，没有网络调用，
没有读取或修改正式 G1/journal/artifact。

### 8.4 最终边界

首轮三项阻塞均已关闭，未发现新的 G4B 冻结合同缺口，因此 R1 Windows 工程独立初验通过。

本轮没有 WSL base 结果，也没有在 WSL `py312` 中运行实际 pyqlib 0.9.7 formal worker；formal 闭环使用受控 fake worker
验证公开 capability、artifact、receipt 与 fresh verifier 闭包。故本 PASS 不替代 Linux/ext4 Gate、py312 实际 Qlib smoke、
真实正式数据运行或 formal G4/M3 Gate。
