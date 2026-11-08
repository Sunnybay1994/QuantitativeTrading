| 轮次 | 真实结论 | 可采用证据 | 不得采用/未运行 |
| --- | --- | --- | --- |
| V1 | `CARRIER_SYNTAX_INVALID_BEFORE_PRODUCT_EVIDENCE` | Python0-call、资源未取得、summary SHA `47755ef671684c5f915629ddba624552c7a84d65c2a083ac620e36a1cbf537b8` | 所有产品阶段UNRUN |
| V2 | `CARRIER_PREFLIGHT_WRAPPER_INVALID_BEFORE_PRODUCT_EVIDENCE` | Parser errors0；Python0-call；summary SHA `60501198f959b2db4383b5c71098a7f1f507eec9b9db16d1c3236313755c633b` | 所有产品阶段UNRUN |
| V3 | 可信产品首失败 | identity PASS；unit full PASS；integration `29 passed / 1 failed`；失败为§13 test-only replay计数；summary SHA `3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f` | Ruff/mypy/cold/scope UNRUN |
| V4 | post-fix产品全部PASS；scope carrier STOP | identity PASS；原失败节点`1 passed`；Ruff exact3 PASS；mypy production PASS；cold PASS；summary SHA `0165770cda42407a1eb9257d85a3e7748c23cd412a70806748906472111c4468` | scope三件套不完整，不能据此宣称scope PASS |
| V5 | scope-only PASS | exact6 count6、cached0、`git diff --check` exit0；stderr仅三条LF→CRLF warning；temp/cache/Python/0xF00清零；summary SHA `d52f14f869ddcfc3840ad0f6ae72738a5a3a549d8079e795022f9dc36d2c60de` | 未重复任何产品阶段 |

V3 unit stdout SHA256=`7f0c60897d815a9e0d812a5ec768f0de50134fbdb41671316b2a62c2d511a2e6`；V3 integration stdout SHA256=
`ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f`。V4 replay node stdout SHA256=
`27b93b41fc7fe0209fb0edde525c85c2884ce93570c953f81487fc13e272dd56`；Ruff stdout SHA256=
`af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af`；mypy stdout SHA256=
`94594db09076fe305d51b50210d0bc5e9d275fb814f8b42c1ed4cf3368392f9a`。

### 14.2 组合结论与剩余边界

以下组合闭合本包Windows工程验证：V3完整unit与integration其余29项 + V4修正节点/Ruff/mypy/cold + V5 exact6/scope/residue。
它不是伪造单轮全绿，也不洗白V1/V2 carrier失败、V3测试失败或V4 scope carrier STOP。状态上限为
`R2F_V2_WINDOWS_ENGINEERING_VALIDATED / SHARED_SCIENTIFIC_CONFIG_CONTRACT_VALIDATED`。

仍未关闭：正式scientific config数值与controlled root（A14）、formal G1 release（A15）、Windows py312/Qlib环境（A17）、actual successor、
真实Qlib、new root、retained resume、acceptance真实运行与M3 Gate。Linux不在当前目标范围，但也不得声明其Gate通过。

### 14.3 提交前职责

1. 同一原implementer仅更新delivery，逐轮记录V1–V5、关键evidence SHA、组合范围与剩余边界；production/tests/review只读，零Python。
2. 同一原reviewer仅更新review，复核evidence root/关键SHA、V3+V4+V5组合、exact6及未验证边界，输出`EVIDENCE_REVIEW_PASS/FAIL`。
3. 只有`EVIDENCE_REVIEW_PASS`后才申请SAFE_COMMIT；ignored evidence不得stage。提交、merge、archive-first退休统一由中央另行裁定。
