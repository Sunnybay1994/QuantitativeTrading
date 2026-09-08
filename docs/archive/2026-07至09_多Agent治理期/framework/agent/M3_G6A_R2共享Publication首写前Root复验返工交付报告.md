# M3 G6A R2：共享 Publication 首写前 Root 复验返工交付报告

日期：2026-08-09  
角色：R1 实现上下文最小返工  
状态：**返工实现与自测完成，等待全新独立上下文复验；不得据此宣布 G6A Gate 通过**

## 1. 唯一阻断与根因

R1 独立初验的唯一阻断是：POSIX 在 formal G6A fresh 完成后把 caller `output_root` rename 并用另一空目录
替换，最终虽然 commit 拒绝且新旧目录均回滚为空，但共享 `ArtifactPublication.write_stream()` 仍通过锚定
dir-fd 执行了三个输出 writer。

根因是旧实现只在 acquire/commit 检查 current path；每次 `_open_output()` 前及 exclusive open 后、caller writer
前没有重新证明路径仍指向原锚定目录实体。

## 2. 最小生产改动

仅修改 `src/quant/research/m3/_artifact_publication.py::write_stream()` 两处：

1. 每个输出 `_open_output(name)` 前调用 `_require_current_root()`；
2. exclusive open、`fstat` 并写入 `_owned[name]` 后，在进入 `os.fdopen` 和调用 caller writer 前再次调用
   `_require_current_root()`。

dir-fd、Windows no-share-delete handle、exclusive flags、owned identity、writer 后 flush/fsync、commit、rollback 和
no-clobber 语义均未改变。第二次复验失败时 descriptor 被关闭，空 owned 文件由既有 identity-aware rollback 精确
删除，caller writer 为 0。

未修改 G1–G6A 业务、数学、manifest、receipt 或公开接口。

## 3. 测试改动

- `tests/unit/test_m3_formal_model_artifact.py`
  - 新增 pre-open 真实 root 漂移探针；
  - 新增“已 open 并记录 owned 后、writer 前”漂移探针；
  - G5A fresh-window root replacement 在 POSIX 明确断言 writer callback 为 0；
  - 同步旧 R4 POSIX 测试期望：新合同在 `write_bytes` pre-open 即拒绝，不再等到 commit 才拒绝。
- `tests/unit/test_m3_formal_prediction_artifact.py`
  - G5B predict-window root replacement 在 POSIX 明确断言 writer callback 为 0。
- `tests/unit/test_m3_formal_evaluation_artifact.py`
  - 同一 formal fixture 内分别在 label fresh 返回后、数学/Parquet bytes 完成后首写前替换 root；
  - Windows rename 被 no-share-delete 阻止并由边界关闭，POSIX rename 成功后由 pre-open 复验关闭；两种模式均
    `writer_calls == 0`，新路径和旧锚实体无 retained bytes。

## 4. 验证结果

### Windows 原生 Miniforge

- R2 五项定向：`5 passed`；
- G5A/G5B/G6A formal publication 三文件全组：`38 passed`，552.67 秒；
- Ruff：共享 production + 三个直接测试文件 PASS；
- mypy `--no-incremental`：`_artifact_publication.py`、model、predictions、evaluate 四生产文件 PASS。

### WSL Miniforge base（`/mnt/f` DrvFS 工作树，pytest basetemp 在 `/tmp`）

- R2 五项真实 POSIX 定向：`5 passed`；
- 同步后的旧 R4 单项：`1 passed`；
- G5A/G5B/G6A formal publication 三文件最终全组：`38 passed`，260.32 秒；
- Ruff：PASS；
- mypy 四生产文件：PASS。

首次 WSL 全组曾得到 `37 passed, 1 failed`，失败仅因旧 R4 测试仍断言“替换后允许写、commit 才失败”；生产
行为已按 R2 正确在 pre-open 拒绝。同步该测试期望后，先单项通过，再以新的唯一 basetemp 完整重跑为
`38 passed`。未隐去该中间失败。

warning 仅为既有 Pandera/Polars deprecation 与工作树 `.pytest_cache` 权限提示，不影响结果。白名单文件在该
工作树仍是上游未跟踪状态，故 Git 无可用 pre/post diff 基线；已记录最终 SHA256，未声称不存在的 Git diff。

## 5. 边界与剩余事项

- 当前 WSL 项目路径仍是 `/mnt/f` DrvFS，不是 ext4；以上只关闭 R2 双平台工程合同，不关闭 Linux/ext4 Gate；
- 未触碰正式 G1 artifacts/journal，未联网、未扫描 `data/legacy`，未 add/commit；
- G6A R2 必须由未参与本轮返工的全新独立上下文复验 PASS，再进入主 Agent 终验；
- 未运行正式全 folds/horizons evaluation，未进入 G6B，不宣称真实数据性能或 M3 Gate 完成。
