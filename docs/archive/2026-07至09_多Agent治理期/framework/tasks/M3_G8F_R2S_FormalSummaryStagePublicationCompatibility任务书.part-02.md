`VALIDATION5` 的 BOM/Parser、argv sentinel 与 exact-worktree identity 均通过；focused exact3 有效执行得到 `9 passed / 14 failed`，14项失败统一发生在 `_stage_bundle` 的 legacy feature fixture 构造，summary stage测试体尚未进入。Ruff、mypy、cold与scope均未运行。证据根为 `artifacts/agent_runs/m3-r2s-validation5-20260826T051500/`；focused stdout SHA-256为 `637a87dc544d47c280233a78b4f6a6eb511d80fc1db3232afbd652a22256b89e`，stage summary SHA-256为 `62a6d5c6ca74d2badc7b108c12a96e533e9ea5ac5467a85d90434630bf5a3246`。

根因是测试夹具复用了同一个外层 `pytest.MonkeyPatch`：formal experiment支持链会对共享 `subprocess` 模块的 `run` 做受控替换；随后 legacy feature fixture 在进入时捕获的已经是该fake，并把它误当作真实 worker callable“恢复”，最终稳定报 `M3_FEATURE_ARTIFACT_INVALID`。这是fixture作用域缺口，不是production失败。

同一原实现者仍仅修改 `tests/unit/test_m3_summary_stage.py` 与delivery；production、其他tests与review冻结：

1. `_publish_formal_experiment_identity` 必须在独立、嵌套的 `pytest.MonkeyPatch.context()` 中执行formal publication支持链，不得复用测试函数的外层monkeypatch。
2. 进入嵌套context前保存共享 `subprocess.run` 的exact callable；formal experiment通过真实public链完成发布并退出context后，必须断言 `subprocess.run is original_callable`，再调用legacy `_SUMMARY._context`。
3. formal fixture内部仍可使用原有受控worker fake；不得以简单交换调用顺序、延长patch生命周期、手工恢复任意callable或monkeypatch experiment verifier掩盖泄漏。
4. legacy feature worker必须捕获恢复后的真实callable；public formal `make_experiment_identity_run_plan` → `StageRunner.run_experiment_identity` → handler → typed output/final verifier、formal receipt stage/path/SHA及全部context同步保持不变。
5. 新增静态/定向断言覆盖：formal fixture内部允许受控fake；退出后exact callable恢复；legacy feature worker使用真实callable；development receipt仍不得进入summary plan/context。
6. 若嵌套context退出后formal artifact不能由真实typed verifier继续fresh复验，立即 `CONTRACT_STOP`，不得绕过verifier或扩大patch作用域。

delivery追加本轮现象—根因—共享模块作用域规则—最小复现—修正测试—通过条件，并保留VALIDATION5的9绿/14失败及后续UNRUN边界。当前仍为 `STATIC_ONLY`，禁止Python/pytest/Ruff/mypy/cold/network/stage/commit。完成后由同一独立reviewer复验；PASS后申请完整 `VALIDATION6`。

## 20. VALIDATION6 CONTRACT_STOP 后的 STATIC_REWORK11：runtime identity 与 worker authority 分域

`VALIDATION6` 的 Parser、argv sentinel与exact-worktree identity均通过；focused exact3有效执行得到 `9 passed / 14 failed`。REWORK10已消除legacy feature侧的worker fake泄漏；14项失败改为统一发生在formal publication后、整体嵌套context退出后的真实 `verify_experiment_identity`，稳定报 `LABEL_ARTIFACT_IDENTITY_MISMATCH`，legacy `_SUMMARY._context`尚未进入。Ruff、mypy、cold与scope均未运行。证据根为 `artifacts/agent_runs/m3-r2s-validation6-20260826T025000/`；focused stdout SHA-256为 `eb49c20321587aa4fcae3a07301ca52430c43b26f13efc09d6b139923e7f1d50`，stage summary SHA-256为 `0a4ff280f6ccf83e593a0c8b6feb31ee999e60c2eb594dce91b6517e92cc19ca`。

中央只读审计确认REWORK10的“退出全部formal fixture monkeypatch后仍fresh verify”要求过强：现有experiment测试支持在确定性测试runtime identity下生成正式provider/experiment；真实typed verifier会fresh调用provider verifier并重算runtime fingerprint。撤销该窄identity替身后拒绝不表示formal receipt或production错误。测试runtime identity替身与worker执行替身属于不同authority，必须分域处理。

同一原实现者仍仅修改 `tests/unit/test_m3_summary_stage.py` 与delivery；本任务书由经理更新，production、其他tests与review冻结：

1. 不再用整体嵌套 `MonkeyPatch.context()` 一次性撤销formal fixture的全部patch。formal fixture允许在外层monkeypatch生命周期内保留确定性的 `build_provider_runtime_fingerprint` 测试替身与StageRunner测试用 `commit_directory_noreplace` 替身。
2. 进入formal fixture前保存共享 `subprocess.run` exact callable。formal publication完成后必须立即、精确恢复该callable；`subprocess.run`、`provider.subprocess.run`、`provider_validation.subprocess.run`及feature侧观察必须全部指向同一真实callable，随后才可进入legacy `_SUMMARY._context`。
3. worker执行替身的恢复不能依赖简单调用顺序、硬编码另一callable或延长fake到legacy链；恢复后 legacy feature必须捕获真实worker callable。
4. 在worker fake已恢复、但确定性runtime identity和StageRunner commit测试替身仍保留的条件下，调用真实typed `verify_experiment_identity`并要求exact对象、manifest/receipt bytes与SHA闭合。
5. 禁止patch `verify_experiment_identity`、`verify_provider_artifact`、任何summary/evaluation verifier，禁止手工构造或改名receipt。formal public chain、receipt/context同步及development receipt隔离保持。
6. 增加异常路径：formal fixture或fresh verify任一失败时，也必须在进入legacy链前恢复共享 `subprocess.run`；不得让cleanup异常覆盖主失败。
7. 若无法在不扩production/其他tests的前提下分离runtime identity与worker authority，立即 `CONTRACT_STOP`，不得弱化typed verifier或延长worker fake。

delivery追加本轮现象—根因—中央合同修正—authority分域规则—最小复现—修正测试—通过条件，并保留VALIDATION6的9绿/14失败及后续UNRUN边界。当前仍为 `STATIC_ONLY`，禁止Python/pytest/Ruff/mypy/cold/network/stage/commit。完成后由同一独立reviewer复验；PASS后申请完整 `VALIDATION7`。

## 21. VALIDATION7 STOP 后的 STATIC_REWORK12：测试真实身份与node选择闭包

`VALIDATION7` 的 Parser、argv sentinel与exact-worktree identity均通过；focused exact3有效执行得到 `21 passed / 2 failed`，说明REWORK11的authority分域已越过此前统一fixture失败。Ruff、mypy、cold与scope均未运行。证据根为 `artifacts/agent_runs/m3-r2s-validation7-20260826T030000/`；focused stdout SHA-256为 `20df397adf95fcc18f13320290dc2fdb2dd95e1f18a46ddc963f0da53d3d757b`，stage summary SHA-256为 `a7ff660e5083a589a996bbbd0ada2f1ec85aab703e4ec490eb397be306d190b3`。

中央只读审计确认两项均为test-only身份选择错误，当前证据不支持production缺口：合法temp用例硬编码 `model_version="v1"`，与bundle真实model/version不闭合，失败发生在temp leaf校验通过后的evaluation identity closure；publication drift用例误以为 `selected[0]` 是h5，但 `select_run_plan_nodes` 按node-id字典序返回，`summary.h10...` 排在 `summary.h5...` 前。`FormalSummaryStagePublicationIdentity.__post_init__` 会独立重算canonical路径，正确篡改目标h5节点应在identity构造时拒绝。

同一原实现者仍仅修改 `tests/unit/test_m3_summary_stage.py` 与delivery；本任务书由经理更新，production、其他tests与review冻结：

1. temp leaf正向用例构造 `FormalSummaryStagePublicationIdentity` 时必须使用 `bundle["model_version"]`，node-id及相关断言同步使用bundle真实model/version；不得为测试修改production temp suffix或evaluation identity规则。
2. publication drift用例必须按exact node_id或 `horizon == 5` 唯一定位h5目标节点，不能依赖tuple位置；只替换该目标节点的publication，再保持完整plan node closure调用 `_select_canonical_summary_node`。
3. 增加显式反例：分别唯一定位h5/h10；篡改非目标horizon不得被误写成当前horizon失败；篡改目标horizon的model_version目录必须稳定拒绝。
4. 不修改、删除或放宽 `_select_canonical_summary_node`、`FormalSummaryStagePublicationIdentity.__post_init__`、typed verifier、temp规则或其它production合同；冗余比较不在本轮重构。
5. 保持authority分域、formal receipt/context、development隔离及所有其它测试语义不变。

delivery追加本轮现象—根因—真实身份/lexicographic选择规则—最小复现—修正测试—通过条件，并保留VALIDATION7的21绿/2失败及后续UNRUN边界。当前仍为 `STATIC_ONLY`，禁止Python/pytest/Ruff/mypy/cold/network/stage/commit。完成后由同一独立reviewer复验；PASS后申请完整 `VALIDATION8`。

## 22. VALIDATION8 完整证据（Windows 工程验证闭合）

经理授权 evidence update。状态仅升为 `R2S_WINDOWS_ENGINEERING_VALIDATED`。**明确未闭合**：R2A、bridge/CLI、actual worker、真实 Qlib、new root、retained、acceptance、`FORMAL_SUMMARY_STAGE_PUBLICATION_COMPAT_VALIDATED` 与 M3 Gate。

### 22.1 证据根与阶段结果

- evidence root：`artifacts/agent_runs/m3-r2s-validation8-20260826T032000/`
- Parser / argv sentinel / exact-worktree identity：**PASS**
- focused exact3：**23 passed** / 39788 warnings / 468.67s
- Ruff：prod2 + tests3 **PASS**
- mypy：prod2 **PASS**
- cold import：prod2 exact **PASS**
- scope：exact8 / cached0 / `git diff --check` **PASS**
- 收口：temp/cache 已清；退出后 affinity `0xF00` 清；受保护 writer PID 7692 / affinity `0x3` 未扰动

### 22.2 阶段 stdout SHA-256

| 阶段 | SHA-256 |
| --- | --- |
| stage summary | `3ff04d776f24b7216abef4eeccad369359ca74c9289743a535ca2cc4dc2e0548` |
| focused exact3 | `fb81b7192ad1cfe7d16709ca518ad72e36eaa9a3a953591956383b55f48165bd` |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` |
| cold | `f72afd3366044b97ee5b46c7f235170a4f0b894255e77f4e87637109e1428279` |
| scope | `abc60e7b60096a8448aa986dca214b6dde7ab99cc5db87a39b0baa06c35da8a2` |

### 22.3 逐轮边界索引（不改写历史正文）

| 轮次 | 边界（历史保留） |
| --- | --- |
| VALIDATION1 | carrier **invalid**（未形成有效 focused 工程边界） |
| VALIDATION2 | carrier PASS；focused **9/14**（F4 h10 fixture 字段归属） |
| VALIDATION3 | carrier PASS；focused **18/5**（F5 canonical work_key/plan） |
| VALIDATION4 | carrier PASS；focused **9/14**（F6 formal experiment receipt） |
| VALIDATION5 | carrier PASS；focused **9/14**（worker monkeypatch 泄漏） |
| VALIDATION6 | carrier PASS；focused **9/14**（fingerprint/worker authority） |
| VALIDATION7 | carrier PASS；focused **21/2**（test identity / lexicographic node） |
| VALIDATION8 | 本轮完整 PASS（上表） |

§15–§21 历史返工合同与证据引用保持原样，不得回写或软化既有 STOP 边界。
