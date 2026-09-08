# M2 R21 SinglePassTrace 独立初验报告

## 结论与独立性

`REVIEW_FAIL / P0=0 / P1=2 / P2=0`。

本 reviewer 未参与 trace 实现或测试修订；此前承担同一任务书的独立设计审查。本轮仅静态审查并新增本报告，
未运行 Python、pytest、Ruff、mypy、网络、真实 data、经济 run 或 ETF 链，未 stage/commit。
实现公式暂未发现确定错误；失败是原生验证证据缺失和冻结测试合同未闭合，不能用静态判断替代实际运行。

权威输入为本 source 的 [任务书](../tasks/M2_R21_RunnerIntegration接入任务书.md) §5.1/§8、
[交付报告](../deliveries/M2_R21_SinglePassTrace交付报告.md)及源码/测试，不借 main 旧任务书。

## 身份与范围

- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace`
- branch：`codex/m2-r21-single-pass-trace`
- HEAD：`085e04488ba1d25bfdb1e3ef497efa148b9e8511`
- implementation：`6fd05834cca189df50b9fa2542df5da56f73e023`
- manager base：`b6998b7e9960eb089bf4e07034f9ed86c94fcbd0`
- Git 父链与上述身份一致；开始 clean，base 到 HEAD 累计仅 production/test/delivery exact3，diff-check PASS。

读取的 Git blob：

| 输入 | blob |
| --- | --- |
| taskbook | 0ca845587bd4cbccd4b3e1d01c6554bb89b8096e |
| classic_eleventh_batch.py | 08f9dae5e13fe4240d34db2fafacdcd540f5a9ea |
| cross_sectional_rank.py | 36198c19f92075ef33f8f1e7ede1b52e1e4c5205 |
| test_classic_eleventh_batch.py | 5237e51b7d90e7ac3230061239a38a65f5b57657 |
| delivery | 23b13405462c2e1e0bda2ebb1681ac2fd653089c |

## 已静态核对的合同

- legacy 和 trace 各自调用一次共享 core；公共 rank 调用点仍只有一次。原特征、rolling sum、ss及相关表达式未变。
- legacy 仍先投影原 bars keys，再做最终非finite检查与正零归一。新诊断校验仅从 trace 入口调用，不返回 partial mapping。
- 三表列序及声明 dtype 与 §5.1 对应；factor keys仅为原bar，observations为完整symbols×sessions，counts每天两组件。
- counts从同次feature/rank关系聚合，合法finite特征下is_not_null与finite计数等价；单成员rank null与多成员ties已区分。
- index<5的pair_count null、index5/6窗口ready但warmup、缺bar lag与lag1零volume边界有源码/测试节点。
- primary_reason优先级与任务书一致；trace检查非finite中间态、pair6且ss缺失及无bar不应出现的ss，legacy不执行这些检查。
- 既有完整rank矩阵、独立手算Pearson与正反相关oracle保留，没有被共享core自比较替换。
- 新tie fixture（test约512–532行）把共同open固定为128。同日各证券使用完全相同的算术输入，消除了不同open重建
  名义相同收益时的横截面浮点差异；这没有改公式、容差或期望rank0.5。只能确认最终fixture设计合理，不能确认
  交付所述attempt02失败及其历史修订过程，因为原生证据缺失。
- 无bar ss故障注入（test约584–613行）仅修改返回grid，保留实际bar factors；可静态确认legacy不进入trace校验。
  它是作用域故障注入，不是正常输入已知生产bug。新旧入口未被证明在所有边界上运行一致。

## P1-1：原生验证证据未在冻结目录保留

位置：交付报告“验证环境与结果”；任务书 §8 原生 stdout/stderr/exit 保留要求。

- 现象：只读盘点批准的 `artifacts/agent_runs/m2-r21-single-pass-trace`，根下只有 `mypy` 子目录；
  递归排除该缓存目录后无文件。未见交付所称pytest-attempt-20260908-01/02/03，也无三阶段原生stdout/stderr/exit。
- 根因边界：当前可证明证据留存合同没有闭合；无法判定历史是否运行、证据是否曾存在或缺失原因。
  mypy缓存不能证明原生exit或通过；报告/transcript不能替代 §8 冻结的落盘要求。
- 最小复现：在上述唯一source root做只读子项及非mypy文件盘点，即得上述缺失结果；未扫描其他任务。
- 影响：23 passed、Ruff/mypy PASS、前两次失败以及PYTHONPATH使editable导入切换至worktree，均未被本次独立核验。
  特别是不能用声明了PYTHONPATH推导实际加载的module.__file__和代码identity。
- 修订建议：原实现链先如实记录缺失及其影响；若原生证据确实仍在获批位置，由中央明确位置/读取授权后核验。
  不得重建历史stdout、编造SHA或把新运行冒充旧attempt。若无法恢复，中央另授fresh验证窗口，保存实际argv、cwd、
  环境、解释器/导入模块路径与生产代码identity、各阶段stdout/stderr/exit，并保留本次证据缺失历史。
- 通过条件：可独立读取的新或原始合规证据闭包，明确Windows-only；旧失败未恢复必须继续标注不可独立核验。
  本review不授权补跑、删除缓存或扩大日志路径。

## P1-2：缺少冻结要求的最终因子正零符号位测试

位置：任务书 §5.1“零值须比较符号位，两个入口均正零”；test约298–613行的新trace测试及delivery“保留正零oracle”。

- 现象：完整测试文件没有copysign、signbit或等价字节/位检查。现有equals、数值相等及approx不能区分+0.0/-0.0；
  两入口同核心相等也不能证明正零。交付称已保留/覆盖正零oracle超出当前源码证据。
- 根因：冻结的bit-level行为要求未落为定向断言；不是本轮已证实生产返回负零。
- 独立对抗/最小数学fixture：使目标证券后六期volume rank为[0,0.5,1,0,0.5,1]，return rank为[0,1,0,1,0,1]。
  两序列均非退化，中心化cross sum精确为0，volume ss=1、return ss=1.5，原负相关表达式可生成负零。
  用已有指数volume构造和共同open=128、整数close差构造真实公共rank；不得伪造rank来替代数学路径。
  对legacy、trace.factors及trace.observations的该非null零值逐一检查符号位为正；保留独立输入/rank矩阵预期。
  这是本 reviewer 未执行的独立反例，不宣称该fixture已加入或已通过。
- 新增测试及通过条件：若遗漏trace最终归一而保留legacy归一，即使数值equals仍成立，符号位测试必须失败。
  同时覆盖trace输入乱序恒等，以及专属非finite中间态/pair6 ss-null拒绝，避免仅以有限ss=1单一注入替代不同拒绝分支。
  返工仅由原实现链修改冻结test/delivery；不因本项顺手重写生产公式、公共rank或参数。

## 交付上限与接续

当前为 `IMPLEMENTED_PENDING_REVIEW_REWORK_AND_VERIFIABLE_WINDOWS_EVIDENCE / ECONOMIC_UNASSESSED / TRIAL0`。
不是Linux Gate、完整runner接入、因子有效性或交易准入。原实现者返工/证据补齐后由同一独立上下文复验；
未获中央新授权不得补跑。本报告不自填其自身SHA，写后身份由只读检查返回。

## REWORK1 同一独立上下文复验

结论：`REVIEW_FAIL / P0=0 / P1=2 / P2=1`。原数学正零P1已关闭；新原生结果确实存在，
但冷导入前置未执行且新增普通测试硬编码解释器，不能将本轮判为完整合同通过。前述FAIL历史原样保留。

### 身份与可见证据

开始HEAD为 `557815c888b3886b76d810bb514b671e46add581`，原source/branch，dirty仅test与delivery。
完整读取source任务书§9、旧review及delivery变更，未使用main替代合同。
production raw SHA为 `3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`；
test raw SHA为 `99ee73c0d7e7b460c98c6a007082c8835fc4da5d2f4040e71f016261ca7ac82f`，与preflight相符。
本次只读证据根为source内 `artifacts/agent_runs/m2-r21-single-pass-trace-rework1`。

独立读取三个attempt-20260908-01的stdout/stderr/exit文件：pytest为28 passed、468 warnings、4.49s，exit0；
Ruff为All checks passed、exit0；mypy为1 source file无问题、exit0；三份stderr均空。
preflight记录cwd、解释器文件身份、白名单环境与argv，Ruff含--no-cache，mypy为新root内cache。
这证明本轮有可读取的新Windows阶段结果，不是旧23pass或旧失败证据恢复。

### 原P1-2与已冻结追加反例闭合

- test约449–530行真实bars构造采用共同open128、整数差和指数volume；真实rank薄spy返回原结果，
  三证券两组件的六期rank均与独立完整矩阵精确相等，没有fake rank。
- 目标A的u/r手算ss为1/1.5、cross为0。三个目标值分别通过item提取，空或多行不能通过；
  随后非null、等于0、copysign=+1，legacy/factors/observations都受检，拒绝空集合vacuous PASS。
- trace三表乱序恒等已加入；非finite cross_ss与pair6 ss-null分别故障注入，legacy保持原bar结果，
  trace抛错且returned仍None。既有finite无barss注入及独立数学oracle保留。production未改。

独立对抗分析：若只删除observations的正零归一，数值equals仍可能通过，但该目标的copysign检查会失败；
若把trace验证移进两入口共同core，则新增注入后的legacy相等调用会抛错，不能通过。以上是源码级反例分析，
本review没有运行mutation或测试。

### P1-R1：普通unit新增机器专属解释器断言

位置：test_classic_eleventh_batch.py:103–105。

- 现象：test_runtime_import_identity_is_current_worktree无条件要求sys.executable为D:\Miniforge3\python.exe。
- 根因：把本次Windows执行准入身份写入可跨平台执行的普通业务unit，混淆验证环境与产品测试契约。
- 最小独立反例：合法WSL base解释器/home/mabw/miniforge3/bin/python加载当前checkout正确模块；
  Path(sys.executable)与Windows字面路径必不相等，该unit失败，即使所有因子行为完全正确。
  本例为静态必然性判断，未启动WSL。
- 规则/最小修订：解释器exact identity应由本次获批preflight采集，不应无条件固化进普通unit。
  删除该机器路径断言；如保留module路径测试，应保持平台无关。不要以跳过全部业务测试修复。
- 通过条件：普通unit不再依赖该Windows盘符；任务环境身份仍在独立preflight中严格核验。

### P1-R2：产品前冷导入身份前置未闭合

位置：任务书§9.2；rework1_preflight.md的module identity行；delivery约108、140行。

- 现象：preflight只记expected and runtime-asserted路径；实际身份验证被放在pytest测试中，
  delivery明确cold未运行。未见产品阶段前的冷导入实际module.__file__输出及独立exit。
- 证据解释：源码断言加28pass支持pytest阶段实际导入与当前worktree一致，不能将它推断为
  先于产品执行的冷导入闸门，或声称保存了原生实际路径输出。
- 最小反例：模块误从main解析且该test失败时，pytest默认仍可继续其他测试；这不满足
  “导入身份不符即停止产品阶段”。不能仅将pytest内断言通过替代冻结时序。
- 修订/通过条件：原实现链如实追加控制偏差；由中央另授fresh窗口，在产品前以限定冷导入
  保存实际解释器/module.__file__/生产identity与exit，不符则三产品阶段UNRUN。
  如中央选择接受替代证据，必须先明确裁定合同偏差，review不得自行追认。本轮结果不抹除。

### P2-R3：delivery并非追加更正，历史段落被替换

位置：delivery HEAD到working diff，85行新增/20行删除；任务书§9.1要求原报告历史保留并追加更正。

- 现象：原“验证环境与结果”、原三个attempt与命令等被替换为摘要，虽然正确声明不可核验，
  但不满足原文保留。Git历史仍可恢复，不是证据永久丢失。
- 最小修订：恢复HEAD中的完整旧delivery作为前缀，将本轮不可核验更正、结果和偏差仅追加于末尾；
  不重写旧FAIL/通过声明的时态。通过条件为原前缀逐字不变、新内容明确覆盖当前状态。

本轮仍只证明上述新Windows阶段结果；完整Windows合同待修，Linux Gate/runner/经济有效性均未完成。
仅追加本review，零Python/测试/真实data/network/stage/commit，不授权任何补跑或清理。

## REWORK2 与 execution-correction1 最终定向复验

`REVIEW_FAIL / P0=0 / P1=0 / P2=1`。原REWORK1两项P1及历史保留P2已关闭；
仅余测试SHA记录转录错误。无需因该文字错误重新运行产品，但须在获批范围追加更正后复核。

### 输入与旧问题闭合

本source HEAD仍为 `557815c888b3886b76d810bb514b671e46add581`。读取source任务书§10、
delivery的REWORK2 STOP及correction全文相关段落、新根各argv/script/stdout/stderr/exit/preflight；
未运行任何Python或测试。开始review SHA为 `ea004bcccd02d1916883f745161278673f872b6cf2bcc8ce98651a1ff5a3d3f0`。

- 普通unit现仅验证相对ROOT的实际模块路径，无Windows解释器硬编码、无skip；原平台污染P1关闭。
- 当前test原生bytes为43625，实际SHA为
  `7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3ababb4a06a677d376`。
  只在内存逆向加回REWORK1的import sys及原解释器断言，得到43725 bytes和
  `99ee73c0d7e7b460c98c6a007082c8835fc4da5d2f4040e71f016261ca7ac82f`。
  因而数学、正零、异常、乱序测试其余内容逐字未改，可依§10复用REWORK1的28pass证据，未声称新全文件SHA不变。
- production无diff，actual SHA仍为
  `3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`，26009 bytes；production mypy证据可复用。
- delivery前缀逐字匹配085e044历史提交的完整原文（Git文本LF前缀比较为true）；原历史保留P2关闭。
  旧验证不可独立核验与REWORK2 SyntaxError STOP仍明确保留，不冒充旧失败恢复。

### 独立读取的新执行证据

根：`artifacts/agent_runs/m2-r21-single-pass-trace-rework2-execution-correction1`。
冷导入argv为executable/-c/完整script三元素，脚本只import目标模块及读取生产文件身份，不调用因子。
原生stdout实际显示D:\Miniforge3\python.exe、当前source的module.__file__、26009 bytes及正确production SHA；
stderr空、exit0。随后identity pytest原生1 passed in 2.23s、exit0；test-only Ruff为All checks passed、exit0，stderr均空。
preflight记录先保存各阶段证据、前阶段exit0才进入后阶段。独立冷导入前置已与pytest内断言分离，原时序P1关闭。
此前REWORK2冷导入stderr确为SyntaxError（脚本文本仅import）、exit1；本次新成功没有替代该历史事实。
本轮只核已有顺序记录及原生证据，不把文件存在性当作独立进程审计或声称重新观察了执行全过程。

### 唯一P2-R4：test SHA被转录成62字符

位置：delivery约147及219行；execution_correction1_preflight.md的test SHA256行。

- 实际Get-FileHash为64字符：
  `7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3ababb4a06a677d376`。
- 上述记录写成62字符：
  `7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3abb4a06a677d376`。
- 根因边界：身份字符串转录错误，不是本轮证实测试文件漂移；不能把不合法长度的字符串当有效SHA256。
- 最小修订：原链在delivery末尾追加唯一勘误，明确列出错误位置、原62字符值、实际64字符值及核验依据；
  保留旧preflight和历史文字，不覆写原始执行证据。明确该错误不影响已核原生结果和数学diff复用，但原SHA记录无效。
- 通过条件：勘误正确绑定当前test bytes/SHA，经原review只读复核；本项不要求重跑、不授权改test/production或清理root。

独立对抗分析：若只凭delivery及preflight相互一致判定身份，两份共同复制的62字符错误仍会被误判通过。
本次以实际文件散列和逆向REWORK1精确散列闭包交叉核验，拒绝该同源错误，不猜补字符。

仅追加本review，其余只读。当前新Windows冷导入/identity/Ruff阶段有效，数学及production mypy按冻结diff复用；
review待上述文字勘误，不宣称Linux Gate、完整runner接入、经济有效或交易准入。

## DELIVERY_ONLY_ERRATUM 最终文本复核

`REVIEW_PASS / P0=0 / P1=0 / P2=0`。仅复核上节唯一P2-R4，现已关闭；不重审或重跑此前已闭合项。

source HEAD仍为 `557815c888b3886b76d810bb514b671e46add581`。
delivery当前22337 bytes，SHA256为
`b600a02558c4d57074b041e2029bf23a3a6070f030ffd550f5a13fad0d4154bd`，与冻结勘误输入一致。
末尾勘误逐处列明delivery两处及execution-correction preflight的旧62字符错误，保留历史，
明确唯一正确64字符SHA为
`7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3ababb4a06a677d376`，与本轮实际Get-FileHash完全一致。
production实际SHA仍为
`3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`；test未变。
勘误没有把旧错误preflight转述为原本正确，也没有把新运行冒充旧证据恢复。

本结论仅为SinglePassTrace包独立初验通过，证据上限保持Windows development validation；
不代表统筹合流、Linux Gate、完整R21 runner接入、经济有效性或PAPER/LIVE准入。
本轮只追加本review，未执行Python/测试/网络/真实data，未stage/commit；提交仍由原授权链另行办理。
