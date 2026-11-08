ordinary`git diff --check`只保留为tracked差异旁证，并必须记录`tracked_untracked_exact6_coverage=0`和
`VACUOUS_FOR_EXACT6`，不得称exact6 PASS。本任务不临时引入未经静态验证的`git diff --no-index`。

exact6的权威闭包改为对每个冻结path分别执行raw-byte卫生与identity复算：

- fresh bytes与SHA256逐字等于执行输入；
- strict UTF-8可解码、no BOM；
- LF-only、CR0、NUL0；
- trailing whitespace count=0；
- single EOF LF；
- path exact、ordinary file、non-reparse、worktree-contained；
- actual untracked set exact6、cached0，无第七个业务path。

上述检查在product前后均执行；任何文件identity、path kind、集合或byte卫生漂移在下一阶段前STOP。taskbook允许的
Markdown hard-break若存在，必须在独立review中逐行冻结为已知例外，禁止笼统放宽trailing whitespace；若当前exact6
无法满足TW0，Validation1必须在Python 0-call时STOP并回经理裁定，不得运行时改文件。root/tool cache、evidence/temp
仍按第12节分别核验，不混入exact6。

### 13.6 返工上限

本轮仍为`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`。
production、test、config、delivery、既有review和roadmap全部只读。同一原reviewer必须仅追加review，确认四项P1、
相邻checkout、外部plugin、双终态和untracked whitespace反例全部闭合。review PASS后中央才可依据`UA-GOV-001`
执行产品阶段；Temp删除仍不由该standing delegation授权。

## 14. Validation1 pre-root配置身份STOP与唯一清单来源

中央依据第12、13节准备Validation1时，在root、资源和Python之前的fresh input-manifest核验发现执行清单引用了不存在的
`configs/research/m2_factor_r15_alpha101_011.toml`，而本任务从第5、8节起冻结的实际exact6配置为ninth-batch
config。中央按首失败停止，原生终态为：

`VALIDATION_CONTRACT_STOP / CONFIG_PATH_IDENTITY_MISMATCH / PRODUCT_NOT_EVALUATED`

该STOP发生在任何evidence/temp root创建、资源取得、Parser product gate或Python前；因此必须记录
`ROOT_CREATE0 / PYTHON0 / PRODUCT_UNRUN / DATA0 / ECONOMIC_IO0 / TRIAL0`，不计产品attempt，不得写成config、因子实现
或测试失败。Validation1原Evidence/Temp roots继续fresh absent，允许在本节review PASS后由一个新的outer exact-once使用；
本次0-call STOP不产生可复用过程证据。

Validation1 input manifest中的唯一配置identity逐字冻结为：

- relative path：`configs/research/m2_classic_daily_factors_ninth_batch.toml`；
- absolute path：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\configs\research\m2_classic_daily_factors_ninth_batch.toml`；
- bytes：3227；
- SHA256：`633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674`。

`configs/research/m2_factor_r15_alpha101_011.toml`及其任何absolute变体均为`VOID / FORBIDDEN_ALIAS`；它不是本任务
文件、兼容名、fallback或迁移入口。任何outer、run contract、identity map、argv或evidence出现该alias，必须在root/
Python 0-call时STOP，禁止通过搜索相似文件、复制、symlink、动态fallback或改名修复。

新outer的input manifest必须从本任务书冻结的exact6 path list逐项派生，并在构造后按固定顺序fresh readback每个
relative/absolute path、bytes和SHA；禁止手工重建文件名、使用历史session列表或从因子名猜配置名。taskbook、
production、test、config、delivery、review六项均须闭合，任何missing/extra/reordered/alias、path containment或identity
漂移均pre-root STOP。第12、13节的roots、Parser、absolute product argv、WorkingDirectory、pytest隔离、resource、
first-failure、Temp删除权限和状态上限全部不变。

本节仍为`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`。
必须由同一原reviewer仅更新既有review复验本次历史与唯一config identity；review PASS后，中央才可依据
`UA-GOV-001`构造新的outer并exact-once执行Validation1产品阶段。

## 15. Validation1 outer root-collision语法STOP

第14节review PASS后，中央构造新的Validation1 outer；但在任何root、资源或Python前，root collision表达式写成
`Test-Path -LiteralPath $ev -or Test-Path -LiteralPath $tmp`。Windows PowerShell将第二个`-LiteralPath`绑定为同一
cmdlet调用的重复参数，导致pre-root参数绑定失败。原生终态为：

`VALIDATION_CONTRACT_STOP / OUTER_CONTROL_PARAMETER_BINDING_ERROR / PRODUCT_NOT_EVALUATED`

本次Evidence/Temp roots均未创建，Parser product stages、Python、pytest、Ruff、mypy、资源取得、data、economic I/O、
business和trial均为0；exact6未修改，roots仍未占用，不计产品attempt。不得把outer控制面错误写成R15因子、test、
config或Windows product failure。

未来Validation1 outer的root collision检查唯一允许的PowerShell源码为：

```powershell
if ((Test-Path -LiteralPath $ev) -or (Test-Path -LiteralPath $tmp)) {
    throw 'ROOT_COLLISION'
}
```

同一outer中的任何布尔表达式如果包含两个或以上cmdlet调用，每个cmdlet调用必须各自完整括号化；禁止以裸`-or`或
`-and`连接尚未闭合的命令调用，禁止依赖PowerShell参数绑定优先级猜测。完整outer source仍须在root、resource和
Python前由`Parser.ParseInput` exact1/errors0验证；实际执行source bytes/SHA必须与Parser输入和run contract逐字同一，
禁止parse后修改或用另一段outer替代。

第12至14节的exact6、唯一config、absolute argv、WorkingDirectory、pytest环境、roots、resource、Temp删除权限、
first-failure和状态上限全部继续有效。本节仍为`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 /
ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`；同一原reviewer复验PASS前禁止启动新的outer。

## 16. Validation1 trailing-whitespace控制证据更正

第15节review PASS后的新outer在pre-root exact6 byte-hygiene阶段报告taskbook存在35个trailing-whitespace行；经理以
`rg`和独立raw-byte LF回扫复核后均得到0。中央随后只读反审计确认35来自outer的PowerShell数组/管道优先级错误，
不是taskbook字节缺陷。权威终态更正为：

`VALIDATION_CONTROL_EVIDENCE_MISMATCH / TRAILING_WHITESPACE_COUNTER_PRECEDENCE_ERROR / PRODUCT_NOT_EVALUATED`

taskbook当时身份仍为34066 bytes / SHA256
`f84f259b9ccf8192c0db6a643231e50e2e5501a80f34832b8a8529b6dd365273`，实际ASCII trailing-whitespace命中0，single EOF
LF存在。错误outer把数组包装放在`-split`左操作数附近，`.Count`没有对预期的完整过滤结果计数；报告样例行的末字节
分别为反引号、字母`t`或其他非0x20/0x09字符，不能作为TW证据。

本次Evidence/Temp roots仍absent，Python、resource、data、economic I/O、business和trial均为0，不计产品attempt；
不得修改或“规范化”本来已经TW0的taskbook，也不得把控制证据错误写成产品失败。

未来outer对exact6的权威TW检查必须使用`ReadAllBytes`：以0x0A为行边界，对每行只从LF前向左回扫连续0x20或
0x09；输出total hit count，并对每个命中输出1-based line number、ASCII suffix count和suffix hex。expected taskbook
TW count为0；任一非零命中必须给出可由raw bytes独立复算的line/hex，不得仅给聚合数。

文本正则旁证已由第17节永久废止；outer不得保留第二套TW算法。完整outer仍须满足Parser输入、实际
execution source和run-contract SHA逐字同源；第12至15节其余exact6、config、roots、argv、resource、Temp权限、
first-failure和上限不变。

本节为`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`；
同一原reviewer仅追加既有review复验PASS后，中央才可使用新outer exact-once执行Validation1。

## 17. Validation1文本TW旁证废止

同一原reviewer复验第16节时确认，原文本旁证中的PowerShell单引号pattern`'[ `t]+$'`不会把backtick escape展开为
Tab；传给.NET regex的字符类实际包含space、literal backtick和字母`t`。只读反例得到：raw-byte权威命中0，错误
文本旁证命中38；字母`t`和反引号被错误命中，真实0x09反而未命中。终态为：

`REVIEW_FAIL / P0=0 / P1=1 / P2=0`

review为49293 bytes / SHA256
`4df08fafbcbb1034fe857522d47c00936be257db687bfce77d81a2bd7e194cf5`。Evidence/Temp roots仍absent，Python、resource、
data、economic I/O、business和trial均为0，不计产品attempt。control-evidence mismatch历史、raw-byte算法和outer同源
合同本身无误；P1只来自多余且错误的第二套文本算法。

本节立即废止所有文本正则TW旁证、文本split、regex匹配和双算法比较；Validation1 outer只允许一套TW authority：

1. 使用`ReadAllBytes`取得冻结文件raw bytes；
2. 以0x0A为唯一行边界；
3. 每行仅从LF前向左回扫连续0x20或0x09；
4. 输出命中总数；每个命中输出1-based line number、trailing-byte count和suffix hex；
5. 当前taskbook expected hit count=0。

固定对抗条件：普通ASCII字母`t`不得命中；literal backtick 0x60不得命中；真实Tab字节0x09必须命中。任何实现若
不能同时满足三项，必须在root/Python 0-call时STOP。禁止再引入regex、`TrimEnd`、Unicode whitespace、shell pipeline
或第三套算法作为fallback；这不会放宽对ASCII space/tab尾随的拒绝。

第12至16节其余exact6、config、absolute argv、roots、resource、first-failure、Temp权限、outer ParseInput/execution/
run-contract SHA同源和状态上限全部继续有效。本节仍为`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 /
ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`；同一原reviewer复验PASS前禁止执行Validation1。

## 18. Validation1产品阶段通过与保留现场收口

中央已执行获批Validation1。本节仅记录既有原生证据，不重跑、不补造文件、不删除Temp，不改公式、方向、参数或历史。
执行HEAD与当前只读HEAD均为 `dfe49df5e8dfd9d929eb8ad196beced1da19715d`。状态仅为
`R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE / ECONOMIC_UNASSESSED / TRIAL0`。

既有worktree-local evidence root为
`artifacts/agent_runs/m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1`：

| 阶段 | 原生结果 | stdout bytes / SHA256 |
| --- | --- | --- |
| focused unit | 23 passed, 258 warnings in 3.75s | 1119 / 6b576f534222b6a6901d3a56e9c167c96bab155c31fc3f4ff74ccf3fa1e3dc97 |
| Ruff | All checks passed! | 19 / 82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18 |
| mypy production1 | Success: no issues found in 1 source file | 43 / 8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff |
| config/cold node | 1 passed in 2.09s | 100 / edfbe512ab5943799cf48447d110ec71dc2a90f7b8e906f1ba9c86ccf7b8a94e |

四个exit文件均为2 bytes / `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`，内容0加LF；
四个stderr均为0 bytes / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。
258条warning为Pandera调用Polars horizontal concat的弃用提示，不顺手升级依赖。
run_contract.json为3789 bytes / `fb632de24a5f9373690dea9169454fd3643f10c5e07187b220cde0dc4b3a555b`；
scope_exact6.json为2502 / `23d8de31144bbf45826b678a5d0aa947bb20b367dde91fda9013d318c8b314e8`；
scope.json为1060 / `1e4187df6ef3c26866a3f10fbbfb5b02ca47b7c5c8a991dcca834d61edbb01ac`；
resource_release.json为79 / `df7ad0f5d23ae5f6dc70c7f2311f11ad98790f92d0312833c6e1020e00bf4b95`，
记录退出时priority=Normal、affinity=0xFFF、python_processes=[]，不冒充未来fresh进程检查。

scope记录actual exact6全untracked、cached0、ordinary diff-check exit0且为 `VACUOUS_FOR_EXACT6`；
不能替代六文件raw-byte身份与卫生证据。Temp在执行后保留，scope记录temp_exists=true；summary、terminal、manifest-last
不存在，符合第13.4节未获删除授权的保留状态，不称完整Windows Gate。Temp仍为
`artifacts/validation_tmp/m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1`。
本节不授权删除、补证、第二终态、产品重跑或修改evidence/temp。

同一原实现者后续仅追加既有 `docs/research/deliveries/M2_RESEARCH_R15_Alpha101011量价极值交付报告.md`；
production/test/config/taskbook/review只读。退出后新独立evidence reviewer仅追加既有review，复核上述原生过程证据，
并挑战“单测通过=因子有效”和“Temp保留=完整闭包”。PASS后由经理申请中央exact6安全提交，不提升运行/退休Gate。
当前无RankIC、Sharpe、真实组合收益、成本容量或市场状态有效性证据；未来仍需public receipt及独立runner/run合同。
本次不构成promotion、PAPER或LIVE准入。经理本轮taskbook-only，PYTHON0/DATA0/ROOT_CREATE0/BUSINESS0/TRIAL0/STAGE0/COMMIT0。
