# M4-P8-RUN-0A：平台、路径与 Runtime 身份独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL（需要返工后重新独立初验）**

## 1. 初验范围与证据

本轮按普通代码质量初验执行，只读检查以下文件：

- `docs/framework/agent/M4_P8_RUN0A_平台路径与Runtime身份任务单.md`
- `src/quant/execution/paper_runtime.py`
- `tests/unit/test_paper_runtime.py`
- `configs/trading/paper_runtime.example.toml`
- `docs/framework/agent/M4_P8_RUN0A_平台路径与Runtime身份交付报告.md`

未修改生产代码或测试，未新增或运行探针，未执行 `git add`/`commit`。测试与静态检查结果仅引用实现交付报告：

- Windows：定向 pytest `16 passed, 1 skipped`；Ruff 通过；mypy 通过；
- WSL `/mnt/f`：定向 pytest `17 passed`；Ruff 通过；mypy 通过；
- 两处 actual formal preflight 均按交付报告记录为非 ext4 拒绝且零写入。

上述结果证明已有用例绿色，但未覆盖本报告列出的配置完整性、文件一致性和类型边界缺口。

## 2. 阻断问题

### 2.1 component proof 没有各业务 verifier 的来源类型边界

**现象**

`_attest_runtime_component(...)` 是同一模块中的通用签发函数，可接收任意 exact role 和任意格式合法的三组
64-hex，并直接返回五类任一 `PaperRuntimeComponentProof`（`paper_runtime.py:412-454`）。现有测试辅助函数也直接
循环五个 role 调用它，以自填 hex 形成完整 proof 集合（`test_paper_runtime.py:80-101`）。

**根因**

当前 attestation 只证明字段由同一通用函数封装并与进程内 key 一致；proof 中没有 ACCOUNT/STORE/GATEWAY/
SOURCE/CONFIG 各自 verifier 的 exact 来源类型或不可混淆 witness。下划线私有命名不是运行时类型边界，
`_verify_components(...)` 也只复核通用 HMAC、role 集合、config identity 和两个 root identity
（`paper_runtime.py:1001-1050`）。

**应遵循规则**

任务单 §5 要求五类 proof 由各自 fresh verifier 在最后一步签发，调用者不能直接构造；exact role 不能替代
exact verifier 来源。

**复现摘要**

持有任意合法 formal config 和 layout 的同进程调用方，可完全照现有 `_formal_components` helper，为五个 role
填入任意 64-hex 并调用通用签发函数；所得集合可通过 `_verify_components(...)`。无需任何业务 verifier 输出。

**必须新增的测试**

- 任意调用方直接使用通用签发路径生成 ACCOUNT/STORE/GATEWAY/SOURCE/CONFIG 时必须拒绝；
- 每一 role 使用另一 role 的 verifier 来源 witness 时必须拒绝；
- 只有各业务 verifier 的 exact 输出类型在 fresh 验证最后一步形成的 proof 可进入 preflight。

**通过条件**

移除或收窄“一个通用函数可签发全部 role”的入口；每类 proof 均绑定各自 verifier 的 exact 来源类型，且
上述跨 role、无 verifier 来源用例 fail closed。

### 2.2 `protected_roots` 只校验非空，允许配置少报

**现象**

loader 对 `protected_roots` 仅要求“非空 list、每项绝对路径、无重复”（`paper_runtime.py:516-521`）；layout
只 fresh resolve 配置实际给出的项目 root 和 protected roots，再据此判断边界（`paper_runtime.py:667-674`）。
测试 fixture 始终只提供一个任意 `tmp_path/protected`，formal config 也能加载
（`test_paper_runtime.py:31-55,237-243`）。

**根因**

必须保护的 G1 release/candidate/journal、M1 journal、P8 既有根等类别没有独立于被校验配置的完整清单或
exact 命名字段。配置本身既声明边界又决定边界是否完整，少报的目录不会进入任何比较。

**应遵循规则**

任务单 §2、§4 和必测反例 2 要求 parent 不得位于全部列明的既有根；“显式提供”仍需具备可验证的配置完整性，
不能把任意非空列表等同于完整列表。

**复现摘要**

formal config 只填一个无关的现存目录作为 `protected_roots`，同时遗漏所有实际 G1/M1/P8 roots；loader 接受，
layout 也只检查该无关目录。被遗漏目录下的 parent 不会因 protected-root 规则被拒绝。

**必须新增的测试**

- 对每一冻结的 protected-root 类别逐项删除配置，loader/preflight 均必须拒绝；
- 用一个无关目录替代完整清单必须拒绝；
- 配置顺序变化可保持等价，但类别缺失、重复类别或类别错配必须拒绝。

**通过条件**

protected-root 完整性由独立可信清单或 exact 命名字段约束；调用者不能通过少报缩小边界，逐项遗漏测试全部
fail closed。

### 2.3 config bytes 已绑定，但 config 文件对象身份未绑定

**现象**

`_read_regular_bytes(...)` 在读取前后比较 `(st_dev, st_ino, st_size, st_mtime_ns)`，随后才执行
`absolute.resolve(strict=True)` 并返回路径与 bytes（`paper_runtime.py:568-586`）。config dataclass 只保留
`source_path`、`raw_sha256` 和解析字段，没有保留文件对象身份（`paper_runtime.py:57-104`）。后续 fresh load
依赖 dataclass equality（`paper_runtime.py:302-304`）。

**根因**

第二次 `lstat` 之后到 `resolve`/返回之间，路径指向的文件对象仍可变化；只要替换文件内容与长度相同，返回的
bytes identity 和后续 dataclass equality 都不能区分原文件对象与替换后的文件对象。fresh reload 比较的是内容
投影，不是同一个配置文件对象的一致性。

**应遵循规则**

任务单 §2、§4、§6 要求 replacement fail closed、fresh 重读 config bytes 并闭合 config identity；文件内容一致
不能替代文件对象一致性。

**复现摘要**

在读取后的窗口把 config path 替换为另一份内容相同、长度相同的 regular file。旧读取结果与新文件的
`raw_sha256`、解析字段和 `config_identity` 相同；当前返回类型没有字段可记录或比较这次文件对象变化。

**必须新增的测试**

- 在 read 后、return 前替换为同内容同长度的不同文件对象，loader 必须拒绝；
- initial load 与 preflight fresh load 之间做同内容同长度替换，formal preflight 必须拒绝；
- existing verifier 前做相同替换，复验必须拒绝。

**通过条件**

配置加载通过稳定文件句柄或等价机制闭合读取对象，并把可复核文件身份纳入 config 一致性；路径解析前后及
fresh reload 均验证同一对象，三类替换测试全部 fail closed。

### 2.4 platform probe 与 layout builder 之间未闭合 parent 目录对象身份

**现象**

platform probe 对 parent 执行 `lstat`，但 proof 只保存 `device_identity`，不保存 parent inode/目录 identity
（`paper_runtime.py:793-853`）。随后 layout builder 才独立计算 `parent_identity`
（`paper_runtime.py:647-708`）。最终 closure 只比较“proof device 与当前 device”以及“layout parent identity 与
当前 parent identity”（`paper_runtime.py:955-963`），没有比较“platform 当时的 parent identity 与 layout 的
parent identity”。

**根因**

platform 和 layout 分别证明了两个时点上的 parent 属性，但缺少两者共享的目录对象 identity。相同 device 上的
parent replacement 不改变 platform proof 已保存的 device 值。

**应遵循规则**

任务单 §2、§3 要求 parent/root replacement 和 mount drift fail closed，platform 与 layout 必须针对同一个实际
parent，而不只是同一 device、同一路径字符串。

**复现摘要**

platform probe 完成后，将 parent 重命名并在同一路径创建新目录；新目录通常保持相同 `st_dev`。layout builder
对新目录生成自洽的 `parent_identity`，closure 的两项现有比较均可成立，但 platform proof 来自旧目录对象。

**必须新增的测试**

- 在 platform probe 返回后、layout builder 开始前做同 device parent replacement，formal preflight 必须拒绝；
- platform proof 中的 parent identity 与 layout parent identity 不同，即使 path/device 相同也必须拒绝。

**通过条件**

`RuntimePlatformProof` 绑定 probe 时的 exact parent directory identity，platform-layout closure 要求它与 layout
保留的 parent identity 完全一致；replacement 用例 fail closed。

### 2.5 `base` 判定没有绑定真实 base prefix 与 executable 的闭包

**现象**

actual probe 分别读取 `sys.executable`、`sys.prefix`、`CONDA_DEFAULT_ENV`、`CONDA_PREFIX`
（`paper_runtime.py:805-808`）。formal verifier 要求环境名为 `base`、`python_prefix == conda_prefix`，并仅对
executable 检查包含 `/miniforge3/`、父目录名为 `bin`、文件名以 `python` 开头
（`paper_runtime.py:901-918`）。它没有要求 executable 位于 `python_prefix` 内，也没有把 prefix 约束为
Miniforge 根 base prefix；`CONDA_DEFAULT_ENV` 是唯一的 base 名称判据。

**根因**

环境名称、prefix 和 executable 是三个并列字符串，没有形成“当前 executable 属于当前 sys.prefix，且该
sys.prefix 本身就是 Miniforge base 根”的文件一致性闭包。一个非 base prefix 可在环境名写成 `base` 时满足
当前条件。

**应遵循规则**

任务单 §3 要求绑定 Python executable/environment identity，并只接受实际 WSL Miniforge `base`；环境名相等
不能单独证明 exact runtime 类型。

**复现摘要**

令实际 `sys.prefix`/`CONDA_PREFIX` 指向 `.../miniforge3/envs/other`，executable 指向该环境的 `bin/python`，
同时令 `CONDA_DEFAULT_ENV=base`。这些字段满足当前全部字符串条件，但 prefix 仍是非 base 环境。另一个未闭合
组合是 executable 与相等的 prefix/conda_prefix 分属不同路径，只要 executable 字符串满足现有形状检查。

**必须新增的测试**

- 非 base prefix 仅把环境名改为 `base` 时必须拒绝；
- executable 不位于 `sys.prefix` 的 exact `bin` 下时必须拒绝；
- `sys.prefix == CONDA_PREFIX` 但二者不是 Miniforge base 根时必须拒绝。

**通过条件**

base 判定同时闭合 live `sys.prefix`、live `sys.executable`、Conda prefix 与 canonical base-root 关系；上述名称/
路径错配均 fail closed。

### 2.6 existing verifier 未重算旧 preflight 的 nested layout/platform 字段

**现象**

`_verify_preflight_attestation(...)` 对 layout 仅纳入 `layout_identity`，对 platform 仅纳入 `proof_digest`
（`paper_runtime.py:1112-1129`），没有从旧 preflight 的 nested 字段重算这两个摘要。existing verifier 虽 fresh
创建 `current`，但最终只比较 config identity、layout identity、platform environment identity 和 component
projection（`paper_runtime.py:373-401`）；它既不 exact 比较 nested layout/platform，也不调用
`_verify_platform_proof_digest(preflight.platform)`。

**根因**

旧 preflight 的 attestation 绑定的是保留摘要，不是 nested 对象的 canonical 投影；fresh 结果也只与这些保留摘要
比较。nested 字段与摘要之间的一致性没有在 existing verifier 中重新建立。

**应遵循规则**

任务单 §6 和必测反例 9 要求 existing verifier fresh 重跑 platform/layout，并在 layout 或 platform proof 任一项
变化后拒绝旧 preflight；保留摘要不能替代 nested 字段重算。

**复现摘要**

用 `dataclasses.replace` 只替换 `preflight.layout.parent`、`parent_identity` 或 root 字段，同时保留原
`layout_identity`；或者只替换 `preflight.platform.mount_point`、filesystem/mount options/probed_at，同时保留原
`environment_identity` 与 `proof_digest`。preflight attestation 的输入不变，existing verifier 的比较字段也不变，
因此当前代码没有路径识别这些 nested 不一致。

**必须新增的测试**

- 分别替换每个 nested layout 字段但保留 `layout_identity`，existing verifier 必须拒绝；
- 分别替换每个 nested platform 字段但保留 `environment_identity`/`proof_digest`，existing verifier 必须拒绝；
- whole-rehash 后仍须以 fresh actual layout/platform exact closure 为准，不能只接受自洽摘要。

**通过条件**

existing verifier 对旧 nested layout/platform 做 exact-type 校验和 canonical identity 重算，并与 fresh actual 结果
逐项或完整 canonical projection 比较；所有 nested replacement 测试 fail closed。

## 3. 测试覆盖核对

现有 17 个测试主要覆盖 mode/key、bytes 变化、development/formal 类型隔离、当前平台拒绝、基本 layout、通用
attestation、pickle/reload 和 import 副作用。以下关键缺口直接可见：

- 没有 `verify_existing_paper_runtime_preflight(...)` 的测试；
- 没有 config 同内容同长度文件对象替换测试；
- 没有 platform 与 layout 两阶段之间的 parent replacement 测试；
- 没有 protected-root 逐类别遗漏测试；
- 没有 non-base prefix 伪装为 `base` 的字段组合测试；
- component 测试由通用签发函数自行生成五类 proof，未证明各业务 verifier 来源边界。

## 4. 初验结论

六项已观察缺陷均由当前代码和测试直接支持，且分别影响配置完整性、文件一致性或类型边界。交付报告中“伪
executable 均拒绝”“parent identity 漂移拒绝”“五类 component typed capability”“existing preflight fresh 重验
闭包”等表述强于现有实现证据。

因此本轮独立初验结论为 **FAIL**。必须按 §2 的通过条件完成最小返工并补齐定向回归测试，再由未参与返工的
全新独立初验 Agent 复验；在此之前 RUN-0A 不得标记通过，M4 状态继续保持
`WAITING_FOR_SOAK_EVIDENCE`。
