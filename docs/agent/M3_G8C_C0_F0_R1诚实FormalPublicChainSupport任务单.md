# M3 G8C-C0 F0 R1：诚实 Formal Public Chain Support 任务单

日期：2026-08-11

状态：**外部实现已停止（DrvFS 上 public G1 publish 需私有 `_renameat2_noreplace` monkeypatch）；未交付 support/integration 代码；待主 Agent 复核；F0/C0/C1 均未宣称 PASS**

## 1. 目标与边界

本包只为 C0 integration 提供一次 pytest session 内、完全由 production public builder/publisher/verifier 构造的
最小 formal `G1 → snapshot → provider → provider-validation → experiment → label/folds/feature → alignment →
model → prediction → target → backtest_plan` 具名发布链。它不是第二套 orchestration，不新增 production API，
不生成可提交的长期金样，不读取用户根项目正式 data，不调用 G7F/G8 StageRunner/tracking/CLI。

权威背景见 `M3_G8C_C0_F0_诚实FormalChainFixture可行性审计报告.md`：留存 bytes 会被 dirty runtime与平台identity
迅速作废；拆 resolver不能替代fresh链；当前唯一诚实方案是在依赖齐全环境按当前runtime现场public publish。

## 2. 环境与平台

- 完整链默认只在 WSL Miniforge `py312` 运行；该环境已有Qlib/LightGBM/fire等G0验收依赖。
- Windows Miniforge与WSL base若`build_provider_runtime_fingerprint`或所需Qlib元数据不可用，必须在写任何G1/stage
  文件前以明确依赖理由skip；不得安装/升级依赖、伪造metadata或把skip写成PASS。
- WSL `py312` 必须实际构建并跑通，不得skip；若public API/依赖仍不能完成，立即停止给精确证据。
- DrvFS只算工程兼容，不是ext4/Gate。

## 3. Test-only public support API

新增 `tests/support/m3_formal_public_chain/`，建议最小三文件：

```python
@dataclass(frozen=True)
class FormalChainLocator:
    project_root: Path
    config_relative: PurePosixPath
    snapshot_id: str
    fold: str
    horizon: int
    g1_release_id: str
    stage_root: Path

def public_formal_chain_session(
    *, project_root: Path, config_relative: PurePosixPath,
) -> ContextManager[FormalChainLocator]: ...
```

可按需要拆为`session_fixture.py`、`publish_mini_formal_g1.py`、`publish_formal_stage_to_backtest_plan.py`，但整个
support应保持窄编排，只调用public API，不复制identity/hash/schema/verifier规则。禁止新增production package导出。

## 4. 诚实构造合同

1. 使用真实`load_m3_config`、`compute_m3_runtime_identity`与`build_provider_runtime_fingerprint`；所有spec/key/receipt
   identity取当前返回值，禁止固定或伪造`code_version`、dependency/provider fingerprint。
2. G1必须通过public `publish_g1_release`并由public `verify_g1_release`恢复；正式G1树精确18文件、无receipt。允许复用
   既有G1测试中的**纯raw input/reference-response fixture数据**，不得复用/替换任何verified capability、production
   verifier或私有issuer。若复用会导致跨测试私有耦合或support超过600行，停止报告，不复制千行fixture。
3. 下游每层使用public builder/publisher、public `publish_stage_receipt`与public verifier，路径精确匹配C0具名布局；
   禁止`common/` alias、SimpleNamespace、`object.__new__`、`object.__setattr__`、`dataclasses.replace` verified、
   monkeypatch production builder/verifier、私有reader/helper/issuer。
4. public builder确实需要外部worker时，只允许项目既有、已冻结的deterministic fake worker/LightGBM执行边界；不得
   fake verifier或直接制造verified返回值。任何使用必须在报告逐项列出，并证明它只替代外部进程而非artifact合同。
5. 写入只限当前隔离worktree下配置指定的ignored `data/clean/m3_g1/releases/<id>`与
   `artifacts/research/m3/**`；开始前exact no-clobber，结束后只删除本session拥有且实体仍匹配的路径。禁止碰根项目
   正式data、联网、MLflow服务、账户/交易路径。

## 5. C0 integration消费与调用计数

把 `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` 的永久stop skip替换为：

1. session support完成后只调用一次`resolve_formal_backtest_cli_inputs`；resolver调用前后G1/stage树exact零写；
2. 返回字段可直接绑定`run_formal_backtest_stage`签名但不运行StageRunner；
3. 13个public verifier调用次数与顺序用`sys.setprofile`/`sys.settrace`按真实函数`__code__`旁路观察；禁止
   monkeypatch/wrap/替换production symbol。若decorator使该方法不能无歧义计数，静态审查exact-once + actual成功可作为
   组合证据，但必须报告限制，不能改production加测试hook；
4. 缺backtest_plan receipt、当前runtime/config漂移、跨平台复用旧树时fail-closed且零写。

## 6. 白名单

- 新增 `tests/support/m3_formal_public_chain/__init__.py`
- 新增最多两个同目录support模块
- 修改唯一 `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`
- 本任务状态
- 唯一交付报告 `docs/agent/M3_G8C_C0_F0_R1诚实FormalPublicChainSupport交付报告.md`
- 独立初验只写 `docs/agent/M3_G8C_C0_F0_R1诚实FormalPublicChainSupport独立复验报告.md`

禁止修改任何production、unit测试、config、既有G1-G8 tests/docs、正式data/artifacts。若必须修改既有test以抽fixture、
support超过600行、需新增第四个support文件或需保留二进制fixture，立即停止重冻。

## 7. 必测与验收

- WSL `py312`：actual session public chain + C0 integration明确PASS；Ruff/mypy/cold import/diff PASS；
- Windows与WSL base：依赖门控在任何写入前明确skip，或若依赖齐全则actual PASS；
- 反例：外部正式data零读取；G1无receipt；same bytes跨platform/旧runtime拒绝；删除plan receipt拒绝；support cleanup
  只删owned路径；hostile外部worker异常不泄漏且不留下半成品；
- 独立初验必须新增未落盘对抗，核对无monkeypatch verifier/verified伪造/私有issuer，并实跑WSL py312 happy-path。

F0仅可声明“诚实public chain test support工程合同PASS”。F0主验PASS后，C0回到R3 integration闭环；不得直接解锁C1。

## 8. 停止条件

任一public层只能靠fake verifier/verified对象、私有helper、伪identity、正式data或长期留存bytes才能通过；完整链需要
联网/MLflow服务；py312依赖不自洽；公共build耗时/体量使session support超过600行或无法在单次3600秒外部会话内
取得明确终态；cleanup无法证明owned-only。命中即停止，不扩白名单、不迁就。
