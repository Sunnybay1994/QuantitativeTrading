# M3 G0：`gym` 单依赖离线构建返工交付报告

日期：2026-07-15  
状态：**阻断：editable 项目构建缺少 wheel-only 构建依赖**

## 1. 已执行的受限例外

确认现有 wheelhouse 为空、权限为 `0700` 且归当前用户所有后，base 仅使用 `pip download` 从官方 HTTPS index
下载了任务书唯一允许的 `gym==0.26.2` sdist，以及 `setuptools`、`wheel` 两个构建工具 wheel；未向 base 安装、
升级或卸载任何包。

| 文件 | 大小（bytes） | SHA-256 |
|---|---:|---|
| `gym-0.26.2.tar.gz` | 721689 | `e0d882f4b54f0c65f203104c24ab8a38b039f1289986803c7d02cdbe214fbcc4` |
| `setuptools-83.0.0-py3-none-any.whl` | 1008090 | `29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3` |
| `wheel-0.47.0-py3-none-any.whl` | 32218 | `212281cab4dff978f6cedd499cd893e1f620791ca6ff7107cf270781e587eced` |

在 `py312` 完全离线安装构建工具并用 `--no-index --no-build-isolation --no-deps` 成功构建
`gym-0.26.2-py3-none-any.whl`，SHA-256 为
`a0bd23864c15ffc128a0a36f771941c08b8effa52c91ac054a13e0675d86d9e2`。核对后仅删除该次下载的
`gym-0.26.2.tar.gz`。

## 2. 完整 wheel 解析与离线安装

重新使用 `--only-binary=:all:`、CPython 3.12/`cp312`/manylinux 目标参数和官方 HTTPS index 下载其余依赖，
成功取得 206 个普通 wheel。wheelhouse 复核结果：非 wheel 普通文件 0、symlink 0、hardlink alias 0；
按文件名字典序的逐文件 SHA-256 清单总 SHA-256 为：

`55f9b398fd56b1ff5111b7c3f0fa0dafb7d222a37e7d1067d5de223d6993051c`

Qlib 由目标下载步骤取得官方 CPython 3.12 wheel；未请求或构建 Qlib 源码，也未出现其他 sdist 需求。

随后两条 `--no-index` 离线安装命令中，`hatchling` 安装成功。第二条 editable 项目安装在元数据阶段失败：

```text
ModuleNotFoundError: No module named 'editables'
```

`hatchling` 的 editable wheel 构建需要 `editables`，但当前任务书只授权 `setuptools`、`wheel` 与唯一 `gym`
sdist 例外；未获授权新增该构建依赖，故立即停止，没有扩张例外或联网。

## 3. 指纹与未完成项

base package-list 在本轮前后保持一致：

| 形式 | SHA-256 |
|---|---|
| 原始 JSON | `568106ba05556241e105fab9b7ce4712a5a5ff4680f87c3160f4f1ab0750d750` |
| canonical JSON | `77329bcb2c14db6cd2925053f4bde047969a3c100cab7b53f0fc192b8de57e78` |

py312 当前 package-list 原始 JSON SHA-256 为
`2e145f22d46ba33355f76745d5c8f96c654a1c16515f5397a4f129089ce2c22b`。

未完成 `pyqlib` 安装、`pip check`、License/版本、Qlib/Alpha158/LGBModel import、readiness、py312 定向测试和
base readiness 全文件测试。wheelhouse 按任务书保留供后续复验；未修改项目代码、测试、配置、路线图、P4C 或既有报告，
且 G0 仍未通过。

## 4. 下一步

主 Agent 必须先决定是否将 editable build 所需的 `editables` wheel 纳入一个新的、明确限定的任务书。不得由本
实现会话自行下载、安装或放宽 wheel-only/单依赖例外。
