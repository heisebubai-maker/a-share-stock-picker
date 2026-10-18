# 开源审查与升级验证 · 2026-10-18

## 选型

实际集成 bukosabino/ta 0.11.0，通过依赖导入 ROCIndicator 和 SMAIndicator；许可证MIT，适合现有Python/pandas本地环境。没有宣称使用AI训练模型。
- https://github.com/bukosabino/ta
- https://github.com/bukosabino/ta/blob/master/LICENSE
- https://github.com/bukosabino/ta/blob/master/ta/momentum.py

审查 Microsoft Qlib（MIT）策略、回测框架。其数据准备、训练及交易模拟需要另行构建数据集，当前日线缓存不足以直接声称提供Qlib模型预测。本次不安装或复制Qlib代码。
- https://github.com/microsoft/qlib
- https://github.com/microsoft/qlib/blob/main/qlib/backtest/exchange.py

审查 Backtrader 原仓库许可证（GPL-3.0）；不将GPL实现复制进当前项目，也不为了名称引入未验证的引擎。
- https://github.com/mementum/backtrader/blob/master/LICENSE

新浪接口字段和分页方式核对AKShare维护者代码；本项目独立编写HTTPS解析与校验，不复制其源码，也不声称数据具有再分发授权。
- https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py
- https://github.com/akfamily/akshare/blob/main/akshare/stock/cons.py

## 验证

全市场实测：接口5576条，沪深支持5225条；40只初筛股加原有持仓完成日线更新。当前策略生成8只观察候选，缺交易状态时新增股数为0。行情日期2026-10-16；2026-10-18为周日，无新增日线正常。

自动测试覆盖参数边界、策略持久化、不同规则、未知状态禁用新增仓位、市值单位、板块过滤、全市场失败保留缓存与持仓纳入、历史信号次日入场与费用、历史报告不读取未来价格。基础测试与新增测试共40项。

已检查JavaScript语法。浏览器自动访问被环境URL策略拒绝，未进行视觉验收，未使用其他浏览器绕过。网页服务和API实测正常。

## 明确边界

本次交付是可编辑规则、市场发现与历史信号验证，并非已完成财务质量研究、新闻解释、全市场历史回测、板块资金流或AI模型训练。原始不复权数据会受除权影响；当前池信号结果存在选池偏差。未给出盈利承诺。
