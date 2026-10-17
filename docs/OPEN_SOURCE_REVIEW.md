# 开源审查与技术路线

审查日期：2026-10-17。范围为上游公开 README、技术栈与许可证页面，不等同于全仓库安全审计。此前对话中的“首选底座”是建议，本次根据本机基础版范围重新评估。

| 项目 | 审查结果 | 第一阶段决定 |
|---|---|---|
| [Quanti](https://github.com/coo-moon/quanti) | FastAPI、Vue、SQLite、因子和选股；还包括账户、订单和代理执行，超出范围。[LICENSE](https://github.com/coo-moon/quanti/blob/main/LICENSE) 为 MIT，版权 Quanti Contributors | 参考分层结构，独立实现，不作为源码底座引入交易模块 |
| [Microsoft Qlib](https://github.com/microsoft/qlib) | 量化研究、模型训练和工作流；依赖与数据准备较重。[LICENSE](https://github.com/microsoft/qlib/blob/main/LICENSE) 为 MIT，版权 Microsoft Corporation | 暂不依赖；后续可作为离线研究候选 |
| [Stock-Picker](https://github.com/cbzhang86/stock-picker) | README 展示多因子与多源数据思路；本次根目录 LICENSE URL 返回404，页面未发现许可证声明，无法确认授权 | 仅功能参考，不复制源码；不将公开可见当作可再分发授权 |
| [StockPicks](https://github.com/wadewen1221/StockPicks) | 多策略、定时任务、回测和网页；README 的架构使用 Tornado。[LICENSE](https://github.com/wadewen1221/StockPicks/blob/master/LICENSE) 为 MIT，版权 Stock Picks V2 Contributors | 参考闭环功能，避免引入完整平台复杂度 |

## 决策

独立实现 FastAPI + Python 标准库 sqlite3 + 原生静态前端。无需 Node 构建，便于 Windows 本地启动。拆分 provider、storage、strategy 和 API。初始版本为模拟模式；后续真实日线更新增加 BaoStock 适配器，显示来源与缓存日期，无AI训练或下单。

无上游代码复制，因而没有捆绑上述项目的许可证文件。将来若复制 MIT 代码，需随复制部分保留相应版权和许可全文；未确认许可证的代码不纳入。

## 直接依赖

FastAPI（MIT）、Uvicorn（BSD-3-Clause）、HTTPX（BSD-3-Clause）、pytest（MIT）。分别参见 [FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE)、[Uvicorn](https://github.com/encode/uvicorn/blob/main/LICENSE.md)、[HTTPX](https://github.com/encode/httpx/blob/master/LICENSE.md)、[pytest](https://github.com/pytest-dev/pytest/blob/main/LICENSE)。安装时保留包内许可证；传递依赖保留其自身许可。模拟数据为本项目生成，不包含第三方行情数据。真实行情接入前须另外核实供应商授权、访问限制和再分发条件。

## 真实日线接口更新（2026-10-17）

新增 [baostock 0.9.4](https://pypi.org/project/baostock/)，发布页许可证元数据为 BSD License，介绍其免费中国股票数据服务。通过SDK调用官方服务，不复制上游源码；安装包及其依赖许可证需保留。公开元数据并不等于行情可任意再分发授权，本仓库不提交下载行情或运行数据库，默认用于本机个人研究。商业使用和再分发应核实供应商条款。

接口依据：[Python API文档](https://github.com/zxygithub/baostock/blob/master/docs/pythonAPI.md)与[发行方示例](https://pypi.org/project/baostock/)。使用匿名login/logout、股票基本资料和日K查询；adjustflag=3为不复权。选用完整ST/交易状态字段，避免依赖股票名称猜测历史状态。单次查询有进程级超时与一次重试，不采用未经核实的多源字段拼接。
