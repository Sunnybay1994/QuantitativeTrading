<!-- Split index for `M4_P8_A1_DurableApprovalReceiptStore独立初验报告.md`; exact source bytes are backed up under `artifacts/maintenance/docs_split_20261109/originals`. -->
原文分卷入口：[第 1 卷](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md) · [第 2 卷](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md)

# M4 P8 A1-R2 独立初验报告
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#m4-p8-a1-r2-%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A)
## 1. 稳定性与范围
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#1-%E7%A8%B3%E5%AE%9A%E6%80%A7%E4%B8%8E%E8%8C%83%E5%9B%B4)
## 2. 静态合同结论
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#2-%E9%9D%99%E6%80%81%E5%90%88%E5%90%8C%E7%BB%93%E8%AE%BA)
## 3. 阻塞发现 F1：raw/index 私有 helper 仍可绕过 hand-off
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#3-%E9%98%BB%E5%A1%9E%E5%8F%91%E7%8E%B0-f1rawindex-%E7%A7%81%E6%9C%89-helper-%E4%BB%8D%E5%8F%AF%E7%BB%95%E8%BF%87-hand-off)
### 现象
### 根因
### 应遵循规则
### 最小复现（静态描述，未执行）
### 通过条件
## 4. 信任边界与能力复制对抗项
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#4-%E4%BF%A1%E4%BB%BB%E8%BE%B9%E7%95%8C%E4%B8%8E%E8%83%BD%E5%8A%9B%E5%A4%8D%E5%88%B6%E5%AF%B9%E6%8A%97%E9%A1%B9)
## 5. 测试路径与证据边界
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#5-%E6%B5%8B%E8%AF%95%E8%B7%AF%E5%BE%84%E4%B8%8E%E8%AF%81%E6%8D%AE%E8%BE%B9%E7%95%8C)
## 6. 复核结论
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#6-%E5%A4%8D%E6%A0%B8%E7%BB%93%E8%AE%BA)
## 7. REVIEW_REWORK1（同一独立审查身份）
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#7-review_rework1%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BD)
### 7.1 基线与漂移
### 7.2 F1 closure：raw/index candidate writer bypass
#### 现象
#### 根因
#### 应遵循规则
#### 最小静态复现（最强 self-consistent HMAC-invalid candidate）
#### 通过条件
### 7.3 非空 close/reopen recovery 与 caller re-verification
### 7.4 新测试真实路径检查与剩余信任边界
### 7.5 执行证据缺口
#### 现象
#### 根因
#### 应遵循规则
#### 最小静态复现
#### 通过条件
## 8. REVIEW_REWORK1 结论
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#8-review_rework1-%E7%BB%93%E8%AE%BA)
## 9. REVIEW_REWORK2（同一独立审查身份；窄 codec 复核）
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#9-review_rework2%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BD%E7%AA%84-codec-%E5%A4%8D%E6%A0%B8)
### 9.1 基线、证据来源与状态
### 9.2 `receipt_id` required-key 修复
#### 现象
#### 根因
#### 应遵循规则
#### 最小静态复现与路径
### 9.3 未回退的 codec 不变量
### 9.4 静态通过条件与剩余证据边界
#### 通过条件
#### 剩余信任边界
## 10. REVIEW_REWORK2 结论
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#10-review_rework2-%E7%BB%93%E8%AE%BA)
## 11. REVIEW_REWORK3（同一独立审查身份；VALIDATION2 import-only cleanup）
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#11-review_rework3%E5%90%8C%E4%B8%80%E7%8B%AC%E7%AB%8B%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BDvalidation2-import-only-cleanup)
### 11.1 基线与交付证据
### 11.2 四个 F401 的窄修复核对
#### 现象
#### 根因
#### 应遵循规则
#### 最小静态复现与当前结果
### 11.3 无行为、测试、schema、migration 或合同漂移
### 11.4 结论与证据边界
## 12. VALIDATION4（同一原始独立审查身份；开发验收证据链复核）
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#12-validation4%E5%90%8C%E4%B8%80%E5%8E%9F%E5%A7%8B%E7%8B%AC%E7%AB%8B%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BD%E5%BC%80%E5%8F%91%E9%AA%8C%E6%94%B6%E8%AF%81%E6%8D%AE%E9%93%BE%E5%A4%8D%E6%A0%B8)
### 12.1 证据来源与身份边界
### 12.2 A1 开发验收证据链判断
#### 现象
#### 应遵循规则
#### 最小静态复现
### 12.3 诚实性与范围结论
## 13. VALIDATION4 结论
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-01.md#13-validation4-%E7%BB%93%E8%AE%BA)
## 14. REVIEW_REWORK4（同一原始独立审查身份；v3 fixture correction）
[↗](M4_P8_A1_DurableApprovalReceiptStore%E7%8B%AC%E7%AB%8B%E5%88%9D%E9%AA%8C%E6%8A%A5%E5%91%8A.part-02.md#14-review_rework4%E5%90%8C%E4%B8%80%E5%8E%9F%E5%A7%8B%E7%8B%AC%E7%AB%8B%E5%AE%A1%E6%9F%A5%E8%BA%AB%E4%BB%BDv3-fixture-correction)
### 14.1 变更边界与证据来源
### 14.2 v3 fixture 的严格升级修复
#### 现象
#### 根因
#### 应遵循规则
#### 最小静态复现与当前结果
### 14.3 其他合同未改变与诚实性
### 14.4 结论
