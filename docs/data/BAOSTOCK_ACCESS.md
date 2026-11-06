# BaoStock 访问约束

业务代码统一调用 `quant.data.connectors.baostock.BaostockConnector`，不要直接调用 SDK。
每次真实 SDK 会话从登录之前到最终关闭 socket 之后，持有同一跨进程文件锁。
占用时最多等待 60 秒，超时抛出 `BaoStockAccessPaused`，由采集任务稍后续跑。
等待不保证先到先得；不会在连接尚未关闭时交给下一个任务。

Windows 共用目录：`C:\ProgramData\QuantitativeTrading\baostock_access`（跟随系统 ProgramData）。
该位置与项目副本和工作目录无关；没有权限时直接失败，不回退到项目私有锁或计数。
部署账号须能读写此目录。未升级的旧代码、其他软件、其他机器不受此约束。

`requests.sqlite` 保存请求计数、黑名单封锁和带进程号的连接事件。
所有发送（包括登录、退出、分页和失败尝试）均先记账，再发送。
滚动 24 小时最多 40000 次，发送间隔至少 1 秒；正常重连间隔 5 秒，异常冷却 60 秒。
退出响应异常会报错，最终仍强制关闭 socket。进程退出后操作系统自动释放锁。

首次部署已从项目 `artifacts/baostock_access/requests.sqlite` 迁移已有状态，原文件仅作备份。
不要删除共用计数库、重新复制旧库或清空黑名单来恢复采集。
当前黑名单暂停须先核实供应商释放，再在共用锁保护下解除本地封锁并单次验证。
计划任务恢复前，应确认所有访问 BaoStock 的项目副本都已使用新版入口。
