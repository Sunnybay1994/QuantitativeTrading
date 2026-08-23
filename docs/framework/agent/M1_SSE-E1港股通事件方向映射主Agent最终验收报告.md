# M1 SSE-E1 港股通事件方向映射主 Agent 最终验收报告

日期：2026-07-17  
结论：**代码合同最终验收通过；既有 clean 数据仍待受控重建**

## 1. 真实根因

主 Agent 通过项目现有官方 SSE 连接器做不落盘探针，当前 1,212 条事件的 `ADJUST_TYPE` 只有“调进”
794 条和“调出”418 条。旧 mapper 判断 `== "01"`，把所有真实事件都落为 REMOVE；旧单测也使用了并非
当前官方响应的 `"01"`，因此形成假绿。

## 2. 交付与职责分离

- 实现：[`M1_SSE-E1港股通事件方向映射修复交付报告.md`](M1_SSE-E1港股通事件方向映射修复交付报告.md)
- 独立初验：[`M1_SSE-E1港股通事件方向映射修复独立初验报告.md`](M1_SSE-E1港股通事件方向映射修复独立初验报告.md)

实现现在只接受去空白后的“调进/调出”；null、空串、旧 `01/02`、英文和未知中文整批稳定抛
`ValueError("SSE_EVENT_ADJUST_TYPE_INVALID")`，不再有 unknown→REMOVE 默认分支。

## 3. 主验

```text
pytest test_connect_market.py + test_eligibility.py   21 passed
ruff                                                    passed
mypy connect_market.py                                  passed
```

修复后的官方端点内存逆推：

| route | 当前快照 | 事件范围 | 事件数 | 逆推启动规模 | 官方规模 | 冲突 |
|---|---:|---|---:|---:|---:|---:|
| SH_CONNECT | 644 | 2014-12-08..2026-07-10 | 1212 | 268 | 268 | 0 |
| SZ_CONNECT | 644 | 2016-12-07..2026-07-10 | 1237 | 417 | 417 | 0 |

官方交叉证据：上交所说明沪港通于 2014-11-17 启动且首批港股通股票 268 只；深交所说明深港通于
2016-12-05 启动且公布港股通股票 417 只：

- https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988794.shtml
- https://www.szse.cn/aboutus/trends/news/t20161125_518836.html

## 4. 剩余风险与下一步

本包只关闭 mapper 代码错误。现有 `data/clean/connect_event/route=SH_CONNECT` 是由旧 mapper 生成的错误
派生数据；普通 upsert 以 action 参与唯一键，会让纠正后的 ADD 与旧错误 REMOVE 并存，不能直接 resume。
下一步先实现“raw 保留、单 route clean 原子替换”的受控工具并独立验收，之后再请求真实数据重建授权。
在重建完成前，不勾选路线图的历史状态机公告核验项，也不发布更早成员区间。
