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
