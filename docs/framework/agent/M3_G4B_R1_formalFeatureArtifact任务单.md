# M3-G4B-R1：formal FeatureArtifact 任务单

日期：2026-08-02
状态：R1 返工与 Windows 自测完成；待独立复验、WSL base / py312 补验与主验

## 目标

在已验真的 formal G1/snapshot/provider/experiment/folds 上发布一个 fold 共享的
Alpha158 `FeatureArtifact`，补齐现有 development-example-only G4B 的正式公共入口。
本包只做 G4B，不接 CLI、模型、预测、评估或正式数据运行。

## 冻结合同

1. 新增正式 `build_feature_artifact` 与 `verify_feature_artifact`，只接受 contracts 中
   exact formal verified types；development capability、普通 dataclass、混配 receipt/root 必须拒绝。
2. development 与 formal 必须复用一套内部构建/验真逻辑。formal worker request 使用
   `release_kind="formal"` 且不得含 `example_id`；development 继续明确
   `release_kind="development_example"`、`formal_gate_eligible=false` 和 `example_id`。
3. Qlib fresh worker 新增独立 formal 子命令；父进程仍不得 import Qlib。worker 必须由 request 中
   已验真 provider/fold/segment/eligible identity 驱动，不读取标签；test inference 输入域绝不含标签。
4. 继续冻结 train-only schema selection、全 NaN train 列剔除、三 segment 精确 eligible keys、
   Float64 logical digest、coverage 与 receipt closure；formal manifest/receipt 的上游必须来自各自
   artifact root，禁止假设同根。
5. build 只写调用者提供的空临时目录；verify fresh 重验 formal G1→G4A 全链与 receipt，拒绝
   extra/missing files、symlink/reparse、path escape、hash/identity/row-order/schema/coverage 漂移。
6. 正式 verified result 必须是 `VerifiedFeatureArtifact`；development result 保持
   `VerifiedDevelopmentExampleFeatureArtifact`，两者不可互换。

## 禁止项与边界

- 无网络，不触碰正式 G1/G2/G8、journal 或现有 artifact。
- 不为测试伪装 development release 为 formal；formal fixture 必须走公开 formal verifier/receipt，
  或从现有严格 formal test support 构造完整闭包。
- 本包通过只关闭 G4B 工程合同，不关闭 formal G4/M3 Gate；Windows 绿测不替代 Linux/ext4 Gate。

## 验收反例

- formal build→receipt→fresh verify 闭环，两个 horizon 复用同一 feature artifact。
- development/formal capability 交叉传入、formal request 多 `example_id` 或错误 release_kind、
  worker 响应身份漂移、receipt 位于错误 root、provider/folds/eligible digest 漂移均 fail closed。
- train 中一列全 NaN 而 validation/test 有值时仍只按 train 剔除；test worker request/输出不含标签。
- Windows 与 WSL base 定向 Ruff/mypy/pytest；如实际 Qlib worker 需要 py312，另报 py312 定向结果，
  不改变 base。
