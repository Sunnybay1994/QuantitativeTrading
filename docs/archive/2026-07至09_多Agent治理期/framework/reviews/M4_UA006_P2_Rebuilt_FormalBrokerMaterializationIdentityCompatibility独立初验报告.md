<!-- Split index for `M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M4-UA006-P2 Rebuilt Formal Broker Materialization Identity Compatibility 独立初验报告
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m4-ua006-p2-rebuilt-formal-broker-materialization-identity-compatibility-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 0. 裁决
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#0-%E8%A3%81%E5%86%B3)
## 1. 范围与只读证据
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E8%8C%83%E5%9B%B4%E4%B8%8E%E5%8F%AA%E8%AF%BB%E8%AF%81%E6%8D%AE)
## 2. 逐项静态核验矩阵
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E9%80%90%E9%A1%B9%E9%9D%99%E6%80%81%E6%A0%B8%E9%AA%8C%E7%9F%A9%E9%98%B5)
## 3. 发现分级
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E5%8F%91%E7%8E%B0%E5%88%86%E7%BA%A7)
### P1-1 — materialized 链允许跨对象身份不一致 / 复用 cold 派生 attestation
### P1-2 — 物化后仍可接受另一枚 `absent-*` broker identity
### P2-1 — 经济投影省略不随 root 物化变化的 `schema_version`（及 account `runtime_config_identity` 不对称）
### P2-2 — 经济漂移测试覆盖面偏窄；多数对抗依赖 `_allow_chain`
### 无 P0
## 4. 实现者未使用的静态对抗反例
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E5%AE%9E%E7%8E%B0%E8%80%85%E6%9C%AA%E4%BD%BF%E7%94%A8%E7%9A%84%E9%9D%99%E6%80%81%E5%AF%B9%E6%8A%97%E5%8F%8D%E4%BE%8B)
### AE-1 — 新 env + 复用 cold policy/binding/account（派生身份不变）
### AE-2 — 物化后换一枚不同的 `absent-*` broker identity
## 5. 五项专项挑战结论
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E4%BA%94%E9%A1%B9%E4%B8%93%E9%A1%B9%E6%8C%91%E6%88%98%E7%BB%93%E8%AE%BA)
## 6. 未运行边界（强制）
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E6%9C%AA%E8%BF%90%E8%A1%8C%E8%BE%B9%E7%95%8C%E5%BC%BA%E5%88%B6)
## 7. 结论
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-%E7%BB%93%E8%AE%BA)
## 8. STATIC_REWORK 复验（P1×2-P2；不擦除上文 REVIEW_FAIL）
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-static_rework-%E5%A4%8D%E9%AA%8Cp12-p2%E4%B8%8D%E6%93%A6%E9%99%A4%E4%B8%8A%E6%96%87-review_fail)
### 8.0 复验裁决
### 8.1 复验范围哈希（起止一致）
### 8.2 授权返工条对照
### 8.3 原发现关闭状态
### 8.4 实现者未使用的新对抗（AE-3）
### AE-3 — 经济与 join 全绿，但 sibling 携带伪造派生身份或无效私有 attestation
### 8.5 发现分级（复验）
### 8.6 未运行边界（复验仍强制）
### 8.7 复验结论
## 9. STATIC_REWORK 复验（VALIDATION2 F3–F5；保留全部历史）
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-static_rework-%E5%A4%8D%E9%AA%8Cvalidation2-f3f5%E4%BF%9D%E7%95%99%E5%85%A8%E9%83%A8%E5%8E%86%E5%8F%B2)
### 9.0 裁决
### 9.1 复验范围哈希（起止一致）
### 9.2 授权条对照
### 9.3 控制流（store bytes 前）
### 9.4 实现者未使用的新对抗（AE-4）
### AE-4 — joins/经济可过，但 materialized env 的 preflight attestation/layout 陈旧
### 9.5 发现分级
### 9.6 未运行边界
### 9.7 复验结论
## 10. STATIC_REWORK 复验（VALIDATION3 F6；保留全部历史）
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-static_rework-%E5%A4%8D%E9%AA%8Cvalidation3-f6%E4%BF%9D%E7%95%99%E5%85%A8%E9%83%A8%E5%8E%86%E5%8F%B2)
### 10.0 裁决
### 10.1 复验范围哈希（起止一致）
### 10.2 授权条对照
### 10.3 实现者未使用的对抗（AE-5）
### AE-5 — 错类型 environment 对象 vs 错类型 policy 对象：错误码必须分叉
### 10.4 发现分级
### 10.5 未运行边界
### 10.6 复验结论
## 11. EVIDENCE_REVIEW（VALIDATION4 ⊕ FINAL_SCOPE_AUDIT；保留全部历史）
[↗](M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#11-evidence_reviewvalidation4--final_scope_audit%E4%BF%9D%E7%95%99%E5%85%A8%E9%83%A8%E5%8E%86%E5%8F%B2)
### 11.0 裁决
### 11.1 冻结面核对（本复验实测）
### 11.2 历史 STOP 保留映射（原生日志）
### 11.3 VALIDATION4 产品绿证据映射
### 11.4 FINAL_SCOPE_AUDIT 证据映射
### 11.5 Gate 宣称边界（无矛盾）
### 11.6 未运行边界（本证据复验）
### 11.7 结论
