# M4-P8-RUN-0A：平台、路径与 Runtime 身份任务单

日期：2026-08-09  
状态：**R3 实现、独立复验与主 Agent 验收 PASS；仅关闭 RUN-0A 环境工程合同，当前 WSL1/DrvFS 仍不能签发 actual formal runtime，M4/ext4 Gate 保持开放**（见 [`M4_P8_RUN0A_R3_环境工程合同主Agent最终验收报告.md`](M4_P8_RUN0A_R3_环境工程合同主Agent最终验收报告.md)）  
前置：M4 P4-P8 工程合同已验收；正式 P8 仍为 `WAITING_FOR_SOAK_EVIDENCE`

## 1. 目标

先建立正式本地 PAPER runtime 的不可混淆边界，不连接 gateway、不注册任务、不创建正式根：

1. strict runtime config 与五个互相隔离的 root layout；
2. actual WSL base + ext4 平台 preflight；
3. account/store/gateway/source/config 五类稳定身份的 typed capability 容器；
4. 只读、无副作用的 `VerifiedPaperRuntimePreflight`；
5. development/Windows/DrvFS 与 formal `PAPER_REAL_TIME` exact-type 隔离。

RUN-0A 通过后，只允许 RUN-0B/C 继续补 semantic verifier 和生产装配。它本身不能生成 P8 manifest、session、
anchor、Gate receipt 或 scheduler XML。

## 2. 路径布局

新增 `src/quant/execution/paper_runtime.py`，定义 `PaperRuntimeLayout`。正式布局精确包含五个 caller-selected
absolute roots：

- `runtime_root`：runtime manifest、OMS store descriptor 和只读 runtime config projection；
- `broker_root`：独立 durable PAPER broker store；
- `evidence_root`：P8 canonical evidence；
- `anchor_root`：P8 append anchors；
- `log_root`：单行脱敏运行日志。

规则：

- 五者必须是同一已存在 ext4 parent 下的真实、互不相同 sibling；互不为祖先；
- build preflight 时五个 leaf 必须都不存在；RUN-0A 绝不创建它们；
- parent 及向上链不得是 symlink；Linux 用 `lstat`/mount identity，Windows development probe 拒 reparse；
- parent 不得位于项目 root、`data/`、`data/legacy/`、G1 release/candidate/journal、M1 journal 或系统 temp；
- protected roots 由调用者显式提供并 fresh resolve，禁止扫描目录发现；
- 路径大小写、drive/UNC、`..`、junction、bind mount、mount drift、root rename/replacement均 fail closed；
- 复制 config 到另一物理 parent 必须改变 layout identity。

正式 root 具体绝对路径留到 RUN-0F 注册前由主 Agent/用户裁定。本包 fixture 只在 development 类型和系统
临时目录测试，不创建 formal leaf。

## 3. 平台 preflight

定义 `RuntimePlatformProof`，包内 actual probe 必须绑定：

- OS、kernel/release、WSL generation；
- Python executable/environment identity，必须为 WSL Miniforge `base`；
- parent mount point、filesystem type、device identity、mount options 的稳定投影；
- probe time（aware UTC）与 proof digest。

formal `PAPER_REAL_TIME` 只接受 Linux、WSL2、WSL Miniforge base、目标 parent `ext4`。Windows、WSL1、DrvFS/
9p/wslfs、未知 mount、conda 环境不明、fake executable 均在任何 mkdir/file/SQLite 之前拒绝。

公共 formal builder 不接受 caller-supplied platform boolean/Protocol。测试如需模拟 ext4，只 monkeypatch 包内
私有 probe；必须另有 subprocess 证明当前 Windows 与 `/mnt/f` DrvFS actual probe 均拒绝且零写入。

## 4. Strict runtime config

新增 `configs/trading/paper_runtime.example.toml`，明确 `mode = "development-example"`，只展示全部必填键；
该文件及其派生 identity 永远不得进入 formal preflight。

新增 strict `PaperRuntimeConfig` / loader：

- exact schema/version、未知键拒绝；
- `mode` 只允许 `PAPER_REAL_TIME` 或 `development-example`，返回 exact different types；
- 五个 roots、relative OMS/broker sqlite filenames、account/source/policy selectors、expected schedule selector、
  runtime version、project root/protected roots；
- 无默认 repo artifacts 路径，无 token/account credential，无网络 URL；
- config identity 绑定 canonical parsed values + retained config bytes SHA-256；
- formal 禁止 `example`、fixture、development、unknown selector；selector 的 semantic registry 留给 RUN-0B。

## 5. 五类身份

定义 exact role：

- `ACCOUNT`：稳定 PAPER account descriptor + initial account snapshot；
- `STORE`：OMS store instance descriptor + trusted runtime root；
- `GATEWAY`：durable broker instance + adapter/policy identity；
- `SOURCE`：formal target receipt + current market/calendar source plan与adapter versions；
- `CONFIG`：TradingConfig + runtime config。

每个身份使用 `PaperRuntimeComponentProof`，包含 role、identity、verification identity、source descriptor digest、
resolved root identity（适用时）和 process-local content-bound attestation。普通 64hex、dict、Protocol、fixture/
development capability、复制/重签 dataclass 不能冒充。

RUN-0A 只提供包内私有 `_attest_runtime_component(...)` 给后续已验收 semantic verifier 调用，不提供公共“签任意
identity”入口，不导出 attestation/key。key 进程本地随机，token 不进入 repr/equality/log/artifact，不可 pickle，
reload 后旧 proof fail closed。后续 RUN-0B 必须在各自 fresh verifier 的最后一步签发；调用者不能直接构造。

五类 proof exact set、role 唯一、root/identity闭包和 runtime config exact match 后，才可返回冻结
`VerifiedPaperRuntimePreflight`。其 identity 绑定 platform/layout/config与五类 component，任何一项漂移必须新 run。

## 6. 公共 API

最小接口：

```python
load_paper_runtime_config(path: Path) -> PaperRuntimeConfig

verify_paper_runtime_preflight(
    *,
    config: PaperRuntimeConfig,
    components: tuple[PaperRuntimeComponentProof, ...],
    now: datetime,
) -> VerifiedPaperRuntimePreflight

verify_existing_paper_runtime_preflight(
    preflight: VerifiedPaperRuntimePreflight,
    *,
    config_path: Path,
    now: datetime,
) -> None
```

formal verifier 必须 fresh 重读 config bytes、重跑 actual platform/mount/path preflight、重验 component attestation 与
exact identity closure。`VerifiedPaperRuntimePreflight` 不可序列化，不是正式 manifest，不写盘。

development 使用独立 `DevelopmentPaperRuntimePreflight`；formal API exact-type 拒绝它。不得以字段相同、继承、
`kind` 字符串或 monkeypatch public input 混用。

## 7. 稳定失败语义

- `PAPER_RUNTIME_CONFIG_INVALID`
- `PAPER_RUNTIME_MODE_INVALID`
- `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`
- `PAPER_RUNTIME_LAYOUT_INVALID`
- `PAPER_RUNTIME_COMPONENT_INVALID`
- `PAPER_RUNTIME_PREFLIGHT_INVALID`
- `PAPER_RUNTIME_VERIFY_FAILED`

所有外部/hostile异常离开 active `except` 后以固定码 `raise from None`，公开 cause/context 均 `None`；traceback
不得包含路径、selector、config 内容、TOKEN、SQL 或 marker。验证失败零写入。

## 8. 写入白名单

```text
src/quant/execution/paper_runtime.py
tests/unit/test_paper_runtime.py
configs/trading/paper_runtime.example.toml
docs/framework/agent/M4_P8_RUN0A_平台路径与Runtime身份交付报告.md
```

本轮不改包根导出，避免重新引入循环依赖；后续 RUN-0D 再做安全惰性导出/CLI。禁止修改 P4-P8 生产代码、
paper gateway/store/cli/service/report/soak、scripts、正式 artifacts/journal。

## 9. 必测反例

1. 五根相同、祖先/后代、不同 parent、已存在 leaf、相对路径、`..`、UNC/drive漂移；
2. repo/data/data-legacy/G1/M1/P8既有根、系统 temp；
3. symlink/junction/reparse、parent/root rename replacement、mount/device漂移、完整 config复制；
4. Windows/WSL1/DrvFS/非base/未知fs actual formal preflight零写入拒绝；
5. example/development config进入formal；未知/缺失/额外键、绝对sqlite filename、credential/URL键；
6. 五类 proof 缺失、额外、重复、角色交换、identity/verification/root/source digest 漂移；
7. 普通64hex/dict/伪Protocol/factory-only capability；
8. old attestation复用到另一合法 component、whole-rehash、pickle/reload；
9. config bytes、layout、platform proof 或任一 component变化后复验旧 preflight；
10. hostile reader/probe/path/component verifier ValueError与RuntimeError脱敏；
11. validation 任何阶段对五个 leaf、parent、repo/artifacts零写入；
12. fresh process import不加载 soak/reporting/backtest，不产生循环导入。

## 10. 验证与平台边界

Windows：定向 pytest、Ruff、mypy；actual formal probe必须拒绝并证明零写入。  
WSL base `/mnt/f`：对应定向验证；actual DrvFS formal probe必须拒绝。  
可用私有 monkeypatch 模拟 ext4只验证纯合同，不得表述为真实 platform Gate。

只有未来在 actual WSL2/ext4 target parent 上运行公开 preflight 成功，才满足 RUN-0A 的真实环境前置；当前开发
绿测只表示代码合同通过。

## 11. 停止条件

- 需要创建/注册正式外部状态；
- 需要用自报 hex 代替尚未实现的 semantic verifier；
- 需要改变 P4-P8 已验收语义或包根导入；
- actual platform 无法可靠区分 WSL generation/base/ext4；
- 需要凭据、网络或真实账户。

## 12. 通过条件

- strict config、actual platform、五根 layout、五类 typed identity、formal/dev exact-type isolation 全部闭合；
- 双平台开发定向绿，且两处 actual 非 ext4 formal preflight都 fail closed/零写入；
- 实现交付、全新独立初验、主 Agent 终验通过；
- 仍不注册、不启动、不创建正式 roots，状态保持 `WAITING_FOR_SOAK_EVIDENCE`。

## 13. R2：环境能力收缩与文件/目录身份闭包（2026-08-09）

独立初验报告：`M4_P8_RUN0A_平台路径与Runtime身份独立初验报告.md`。R1 结论 FAIL。

### 13.1 失败闭环

1. **万能 component signer**：`_attest_runtime_component` 不要求任何 account/store/gateway/source/config
   semantic verifier的exact capability；同模块调用者可直接为任意hex生成五种 proof，public formal API接受。
   `_COMPONENT_KEY`作为模块属性也不是来源边界。R1测试正是用该通用函数生成“formal components”。
2. **protected roots可少报**：`protected_roots` 只是调用方提供的非空字符串列表，没有required role/exact set或
   当前project/G1/M1/P8权威root闭包；少报即可绕过禁止路径。
3. **config ABA**：config对象只绑定path/content identity，不绑定初次load的文件对象/父目录identity；同路径
   替换为另一同长度合法config后可被当作fresh输入。
4. **parent TOCTOU**：platform probe与layout build之间替换parent真实目录，platform proof与layout分别自洽，
   但两者没有要求同一parent inode/file-id，formal preflight仍可成功。
5. **base环境伪装**：仅凭`CONDA_DEFAULT_ENV=base`接受实际位于`.../envs/py312`的prefix/executable；没有绑定
   项目冻结的WSL base真实prefix与解释器。
6. **nested drift**：existing verifier只信缓存的`layout_identity/proof_digest`与outer attestation，没有fresh重算
   nested layout/platform所有字段；保留旧摘要/token、替换nested值仍通过。

这些问题共同破坏“actual环境/路径/身份只能由fresh verifier证明，调用者不能自报”的系统不变量。

### 13.2 R2 架构裁定：RUN-0A只证明环境，不签业务身份

R2收缩RUN-0A输出：

- 删除/停止使用通用`PaperRuntimeComponentProof`、`_attest_runtime_component`和接受五种component的formal
  preflight；不得通过改名保留万能signer。
- RUN-0A唯一formal capability改为`VerifiedPaperRuntimeEnvironment`（名称可等价），只绑定strict config、actual
  platform、五根absent layout和fresh时间；public verifier不接受任何业务hex/component。
- ACCOUNT/STORE/GATEWAY/SOURCE/CONFIG五类semantic身份推迟到RUN-0B1/B2/C，由各模块自己的exact verified
  dataclass与fresh verifier生成。最终`VerifiedPaperRuntime`必须组合五种不同exact type，不能共享一个
  role+hex容器或通用attestation key。
- development保持exact不同类型。R2 formal environment仍不是runtime manifest、runner或Gate capability。

本节取代§5中“RUN-0A通用签发五类proof”和§6中formal API的components参数；角色与必须绑定的语义清单仍
作为RUN-0B/C要求保留。

### 13.3 config与权威root

1. config schema/version升级（建议`paper-runtime-config-v2`），R1 config/preflight exact-type拒绝。
2. loader通过no-follow regular file handle读取；在打开前后/fstat绑定config file identity与parent directory
   identity，并将其写入冻结config对象。fresh reload必须与初次file/parent identity相同；rename/replacement、
   bytes相同或同长度ABA均拒绝。
3. `project_root`不能由config自报。由当前`paper_runtime.py`真实resolved源码位置推导项目root，config字段若
   保留必须与actual root exact equal；formal layout无条件拒绝actual project root及其全部后代。
4. 删除自由字符串`protected_roots`，或改成exact-key required role map并由后续semantic capability fresh证明。
   RUN-0A至少保护actual project root和system temp；外部G1/M1/P8/store roots由RUN-0B/C exact capability加入
   最终overlap verifier，调用者不能少报。
5. example config同步v2与新exact keys，仍是development exact type。

### 13.4 platform/layout同对象闭包

- `RuntimePlatformProof`必须包含probe时parent physical identity；layout build后该identity必须等于
  `PaperRuntimeLayout.parent_identity`，并在返回前再fresh核对。
- formal WSL base绑定actual `sys.prefix`、`sys.executable` resolved identity，必须精确是项目冻结的
  `/home/mabw/miniforge3`与其base解释器；环境变量只能作为附加一致性检查，不能决定base。
- platform proof digest与layout identity都必须从nested字段fresh重算。existing verifier先重建/重算nested
  proof/layout，再核对outer environment attestation；任何cached digest与nested不一致拒绝。
- actual Windows与WSL1/DrvFS继续在任何leaf写入前拒绝；模拟ext4仍只用于纯合同测试。

### 13.5 R2必测与通过条件

- public formal API签名不再接受component tuple/普通hex；模块中不存在可调用的通用业务proof signer；
- R1任意五hex路径编译/运行失败，且RUN-0B尚未实现时不能构造formal business runtime；
- config same/different bytes、同长度ABA、parent rename replacement、symlink/reparse均拒绝；
- config project_root伪报、protected roots少报的R1路径不存在或拒绝；
- platform probe与layout间parent replacement，返回前parent replacement均拒绝；
- py312 prefix/executable配`CONDA_DEFAULT_ENV=base`仍拒绝；真实base+模拟ext4纯合同通过；
- nested layout任一root/parent/root identity与platform os/kernel/fs/mount/prefix/executable变化，保留旧digest/outer
  token也被existing verifier fresh拒绝；
- hostile reader/probe/path异常cause/context/traceback脱敏、零写入；
- Windows与WSL base定向pytest/Ruff/mypy通过；当前两平台actual formal均unsupported/零写入。

R2实现后必须由全新独立上下文复验。通过只关闭RUN-0A环境工程合同；RUN-0B1 durable broker、RUN-0B2
production loaders/risk、RUN-0C schedule、RUN-0D runner与真实WSL2/ext4仍全部开放。

## 14. R3：formal environment 唯一签发路径（2026-08-09）

R2独立复验报告：`M4_P8_RUN0A_R2_环境能力收缩与身份闭包独立复验报告.md`。R1六项已关闭，但R2仍FAIL。

### 14.1 失败闭环

模块仍暴露可直接调用的`_build_environment`与`_sign_environment`。普通调用方可在unsupported Windows和
system temp roots下自行执行`load formal config → development layout helper(allow_system_temp=True) → actual
platform projection → generic build/sign`，获得exact `VerifiedPaperRuntimeEnvironment`，且attestation verifier
通过。该路径绕过public formal API的WSL2/ext4、system-temp、parent返回前fresh closure。

R2删除了业务component万能signer，但保留了环境万能signer，仍违反“formal environment只能作为完整actual
verifier成功后的返回值”不变量。

### 14.2 最小返工规则

1. 删除模块级、接受caller projection后即可mint formal capability的`_build_environment`、`_sign_environment`
   或任何等价generic signer/builder；不得仅改名。
2. formal capability的key与构造逻辑放入模块初始化创建的私有closure；closure唯一mint分支必须先在同一次
   调用内完成：fresh config file/parent identity、actual project/layout、actual platform/base/ext4、platform-
   layout parent同一性、返回前fresh root/config检查。不能接受调用方预先构造的layout/platform proof。
3. public `verify_paper_runtime_environment(config, now)`是唯一签发入口；existing verifier只能fresh调用同一
   actual path得到current environment，再做exact比较。development verifier不能进入formal closure。
4. 可以保留只读layout/platform helpers供development与测试，但它们单独或组合不能取得formal token/type。
5. verifier-only attestation检查函数可保留；不得提供sign arbitrary content能力。R3只要求普通模块调用边界
   无generic mint入口，不宣称抵抗任意Python解释器内省/内存读取。

### 14.3 新增测试与通过条件

- 静态/运行时确认模块不存在`_build_environment`、`_sign_environment`及等价接受layout/platform后签formal的
  callable；不存在模块级formal signing key；
- R2复现路径在Windows/system temp只能得到development值或稳定unsupported，不能构造exact formal type；
- 单独调用layout/platform helper、伪proof、普通dict/object.__new__不能通过existing verifier；
- public formal API在Windows与WSL1/DrvFS继续unsupported且五leaf零写入；模拟ext4 happy path仍只经public API；
- existing verifierfresh调用同一actual path；config/root/platform/nested drift回归继续通过；
- hostile内部closure异常固定脱敏，cause/context为空；双平台pytest/Ruff/mypy通过。

R3通过仍只关闭RUN-0A环境工程合同，不创建正式root，不启动或注册soak。
