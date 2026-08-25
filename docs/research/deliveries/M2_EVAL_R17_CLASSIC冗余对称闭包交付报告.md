# M2-EVAL-R17 classic 冗余对称闭包交付报告

## 结果

- task id：`M2-EVAL-R17-CLASSIC-REDUNDANCY-SYMMETRY`
- 状态：`DELIVERY_READY / VALIDATION_DONE_PENDING_EVIDENCE_REVIEW`
- exact base：`a063f56651ab3af6380a4c07a5ea3bf38fcffb8c`
- branch：`codex/m2-eval-r17-classic-redundancy-symmetry`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-eval-r17-classic-redundancy-symmetry`

## 改动与证据

实现一个 `_aggregate_redundancy_by_factor` 私有 helper，统一处理通用入口、market-risk、fourth-batch、
fifth-batch 四个 classic 调用点。helper 从 `factor_a`、`factor_b` 两侧收集每个 summary candidate 的全部
incident，并取 `median_abs_rank_corr` 最大值；candidate-candidate pair 同时约束两侧，summary 外的
reference/control 不生成 summary 行，并保持 summary 行集与顺序。

helper 在 join 前稳定拒绝缺失字段、严格 String 违规、null/空字符串、非法 status、非有限或 bool 相关值、
重复 summary factor、重复或反向重复 pair。无 incident candidate 输出空聚合值，由既有 redundancy gate
fail-closed 为 `REJECTED`；已有 `REJECTED` 不升级。阈值、相关性计算、经济门禁、配置、schema、output、
历史状态及其他 Gate 均未改变。

新增/调整测试覆盖：factor-a/factor-b 对称聚合、candidate-candidate 双侧约束、reference/control 行集、
无 incident、summary/pair 重复、缺失及严格类型字段、null/empty、bool/NaN/正负 infinity 相关值、输入及
端点顺序不变性、已有 `REJECTED` 保持，以及四个调用点共享 helper 的静态计数。

## F1 rework evidence

- phenomenon：单行 `(candidate, candidate, 0.10)` self-pair 在原 helper 中通过 canonical pair 检查，
  可能以有限且低于阈值的相关值满足 redundancy gate。
- root cause：原逻辑只检查 canonical pair 是否重复，没有在聚合前要求 `factor_a != factor_b`；冻结
  evaluator 只生成两个不同端点的 pair，因此该输入不是合法 evaluator incident。
- rule：self-pair 不能形成两个端点的 redundancy pair，必须在 aggregation/join 前稳定 `ValueError`；
  普通 distinct candidate-reference pair 继续合法。
- minimal reproduction：

  ```python
  summary = pl.DataFrame({
      "factor": ["candidate"],
      "research_status": ["RESEARCH_ONLY"],
  })
  redundancy = pl.DataFrame({
      "factor_a": ["candidate"],
      "factor_b": ["candidate"],
      "median_abs_rank_corr": [0.10],
  })
  _aggregate_redundancy_by_factor(summary, redundancy)
  ```

- added test：`test_candidate_self_pair_is_rejected_before_aggregation` 使用单个 finite below-threshold
  self-pair，并断言 `ValueError`；既有 distinct candidate-reference 测试保持不变。
- pass condition：helper 在 correlation maximum/incident aggregation 前拒绝所有 self-pair，distinct
  candidate-reference pair 仍按原合同通过；本轮仅完成静态证据，禁止的 runtime checks 未运行。

## P1 test-message rework evidence

- phenomenon：retry01 selected validation reached the focused self-pair test, but its regex expected
  `distinct endpoints` while production raised `classic redundancy pair endpoints are not distinct`。
- root cause：测试断言使用了与现有稳定生产消息不一致的 longer fragment，导致正确的 `ValueError` 被误判为失败。
- rule：focused test must match the stable production fragment `not distinct`；不得改变生产消息或其他合同。
- minimal reproduction：单个 `(candidate, candidate, 0.10)` self-pair 触发 `ValueError("classic redundancy pair endpoints are not distinct")`，
  并以 `match="distinct endpoints"` 断言，pytest reports regex mismatch。
- added test：将 `test_candidate_self_pair_is_rejected_before_aggregation` 的 `pytest.raises` match 精确收窄为
  `not distinct`；未修改其他测试或生产代码。
- pass condition：该 focused test 的断言匹配现有生产消息，self-pair 仍在 aggregation 前 fail closed；本轮只完成静态
  测试消息修正，禁止的 Python/pytest/Ruff/mypy/cold-import/checks 未运行。

## Mypy typing rework evidence

- phenomenon：post-P1 validation 在 `mypy src/quant/research/run_classic_factors.py` 阶段停止，报告三项类型错误：
  `float(Number | Decimal)` 两项，以及 canonical pair 被推断为 `tuple[str, ...]` 一项。
- root cause：helper 仍以过宽的 `numbers.Number` 表达 correlation，mypy 无法证明 `float` 输入契约；
  `tuple(sorted((factor_a, factor_b)))` 也未显式表达固定二元 tuple 形状。
- governing rule：先拒绝 bool，再只接受 `int | float | Decimal` 并以该窄类型保留 finite 检查；canonical pair
  必须显式构造为 `tuple[str, str]`；不得改变阈值、相关性/经济公式或其他行为。
- minimal reproduction：

  ```python
  maximum_by_factor: dict[str, Number | Decimal] = {}
  numeric_correlation = cast(Number | Decimal, correlation)
  pair = tuple(sorted((factor_a, factor_b)))
  ```

  对上述源码运行 `mypy src/quant/research/run_classic_factors.py`，分别产生 `float` 参数类型不兼容和
  `set.add` 需要 `tuple[str, str]` 的错误。
- tests：本轮仅完成静态生产类型修正；未运行 Python、pytest、Ruff、mypy、cold import 或其他 checks，
  未修改测试；既有 validation logs/basetemps 保持不变。
- pass condition：correlation 的 bool-first/narrow numeric/finite 语义和 canonical pair 去重语义保持不变，
  源码可通过 mypy；本轮状态仍为 `STATIC_DONE_REWORK / STATIC_ONLY`，等待后续授权验证。

## 静态验证与范围

- 已核对 HEAD 为 exact base，分支为任务书冻结分支。
- 已用 `rg` 核对 helper 为一个定义加四个调用点；生产文件不再包含 `group_by("factor_a")` 或
  `right_on="factor_a"`。
- `git diff --check` 通过。
- 本 worker 仅写入以下三条白名单路径：
  - `src/quant/research/run_classic_factors.py`
  - `tests/unit/test_run_classic_factors.py`
  - `docs/research/deliveries/M2_EVAL_R17_CLASSIC冗余对称闭包交付报告.md`
- manager-owned taskbook/roadmap 未修改；未创建 branch/worktree，未提交 commit。

## 验证结果、证据与未运行项

- stage1 native PASS：identity probe exit `0`；collect-only exit `0`，`65 tests collected`。
- stage2 native PASS：严格 15 个 nodeid 顺序执行，`30 passed`，exit `0`。
- stage3 native PASS：Ruff source/test exit `0`。
- stage4 native PASS：mypy source exit `0`。
- stage5 native PASS：cold import exit `0`。
- stage6 exact6 PASS：Stage6-only `01-exact6-scope` 使用
  `git -c core.quotePath=false` 的 UTF-8 NUL 枚举，tracked `3`、untracked `3`、combined `6`、unique `6`，
  与冻结 exact6 set 完全一致，exit `0`。
- cached/diff PASS：Stage6-only `02-cache-diff-check` 报告 `cached=0`、`diff_check=PASS`，exit `0`。
- temp/process evidence：仅作为 manager 同窗口 side evidence；不将其声称为原始 stage persistent
  stdout/stderr/exit 三文件集合的一部分。Stage6-only carrier 在建立 item3 时停止，因此不宣称 temp/process
  item 有 PASS 或对应的 persistent three-file set；历史 evidence roots 与已生成日志均保留，未清理。

### Persistent log SHA evidence

以下路径均相对于 worktree；`bytes` 与 SHA256 为只读采集值。

- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/01-identity-probe.stdout.log`：1248；`64308C9C691448DCF9B1E7B4383AED34CE6A2BFBF05E62C133F747528C14F118`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/01-identity-probe.stderr.log`：2；`7EB70257593DA06F682A3DDDA54A9D260D4FC514F645237F5CA74B08F8DA61A6`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/01-identity-probe.exit`：845；`ACD180504FE53C1225A4A0A9D954007A1F8DDDDC3F5DA7F199A361EF1CB7D49F`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/01-collect-only.stdout.log`：8009；`03E3A39994976289D0879EE81EBD981EDB4D6B379F828BF7E3D396F2E39E522E`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/01-collect-only.stderr.log`：2；`7EB70257593DA06F682A3DDDA54A9D260D4FC514F645237F5CA74B08F8DA61A6`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/01-collect-only.exit`：840；`0D5CE3753AB89A94BBC8C2EA08AC308D670A15991F7A87BD2A20FDF5A47DD3F1`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/02-selected-tests.stdout.log`：2517；`9896BE2077C45811F9768E3B86392F413C8B509C14FF65173D6F370CF5C36B32`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/02-selected-tests.stderr.log`：2；`7EB70257593DA06F682A3DDDA54A9D260D4FC514F645237F5CA74B08F8DA61A6`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/02-selected-tests.exit`：2414；`71F9CCEE79AC7D8BE2A55D9BE29BDEB8B4548A243B79280B3BF8AEC754BDFB28`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/03-ruff.stdout.log`：598；`4B971277308E2F45F8CC3B7829A895BBF156EEFBDD96FA5BBE311660AA776AE0`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/03-ruff.stderr.log`：2；`7EB70257593DA06F682A3DDDA54A9D260D4FC514F645237F5CA74B08F8DA61A6`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/03-ruff.exit`：577；`7DE1844F9F172D7D916C7164480F0DD0F79DCE034DA2FC9FCFDB7E48D8E8111E`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/04-mypy.stdout.log`：561；`E74FCA9394EA3CCDB7E21ADE450644C0013293B6864A2A358BD0D464A8FC2A80`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/04-mypy.stderr.log`：2；`7EB70257593DA06F682A3DDDA54A9D260D4FC514F645237F5CA74B08F8DA61A6`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/04-mypy.exit`：516；`DF198FD907EB47E96EE12288D3BA6670DF307E2B3ABDB3693034C2B3D12C27E5`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/05-cold-import.stdout.log`：607；`A1C44065052B4671B3492828FEF910D09E807CFBA243DBE5E6E4904503D917A5`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/05-cold-import.stderr.log`：2；`7EB70257593DA06F682A3DDDA54A9D260D4FC514F645237F5CA74B08F8DA61A6`
- `artifacts/test_tmp/m2-eval-r17-central-validation-20260825-203527872-63c3d27731f14af698f035a576fb36aa/logs/05-cold-import.exit`：557；`53C34BA6EDCA3B4F5E72EBB9B8607B1A8F0666AB7040C829878E35F760D38912`
- `artifacts/test_tmp/m2-eval-r17-stage6-only-20260825-204417246-9794561c5b2f494b99a4acc7b3de97f8/logs/01-exact6-scope.stdout.log`：650；`5AE114DC052FA99EA5C067460B3D8554288B5824137C297BF28D28C1CBEB1C74`
- `artifacts/test_tmp/m2-eval-r17-stage6-only-20260825-204417246-9794561c5b2f494b99a4acc7b3de97f8/logs/01-exact6-scope.stderr.log`：425；`35CFA392B18FA76FE4186355CE204596A6FB388612269CAB7CA617A1232BF8A8`
- `artifacts/test_tmp/m2-eval-r17-stage6-only-20260825-204417246-9794561c5b2f494b99a4acc7b3de97f8/logs/01-exact6-scope.exit`：130；`19F659A6E2263957EB143ADD4DAAE2DE736E15A709F111B2068D126814ED64F5`
- `artifacts/test_tmp/m2-eval-r17-stage6-only-20260825-204417246-9794561c5b2f494b99a4acc7b3de97f8/logs/02-cache-diff-check.stdout.log`：181；`E7617E7ACCE721D369CB095397ECF4156371FEE873EDF001FEEF92A067B318D3`
- `artifacts/test_tmp/m2-eval-r17-stage6-only-20260825-204417246-9794561c5b2f494b99a4acc7b3de97f8/logs/02-cache-diff-check.stderr.log`：425；`35CFA392B18FA76FE4186355CE204596A6FB388612269CAB7CA617A1232BF8A8`
- `artifacts/test_tmp/m2-eval-r17-stage6-only-20260825-204417246-9794561c5b2f494b99a4acc7b3de97f8/logs/02-cache-diff-check.exit`：134；`6D67A4ADBAE3CA38A76DFCF90ED9EE4900DAB0D509D09CCDBB6E721574FC1442`

本轮仍未运行 real run、网络、data/raw、ledger、financial clean/partial financial raw I/O，也未清理或移除
任何 evidence directory；未执行 merge/rebase。
