# A股智能选股复盘系统 · 第一阶段

Windows 本地网页版，FastAPI + SQLite + 原生 HTML/CSS/JavaScript，无需 Node.js、Docker 或行情账户。提供可解释的规则评分、日期筛选、每日复盘和持久化笔记。

**当前只提供模拟数据。** 12 个虚构样本、70 个工作日（非真实交易日历），固定截止 2026-10-16；不随当前日期更新。样本代码 DEMO01–12 不是证券代码。无自动下单、无真实收益或盈利概率承诺，不构成投资建议。

## Windows 启动

1. 安装 Python 3.12（勾选 Python Launcher 和 pip）。
2. 下载或克隆本仓库，双击 `start.bat`。首次启动需要联网安装依赖。
3. 浏览器访问 <http://127.0.0.1:8000>。选择日期 → 查看评分 → 生成复盘 → 填写并保存观察记录。
4. 在启动窗口按 Ctrl+C 停止。再次启动会保留笔记。

也可在项目目录手动执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

端口冲突时改为 `--port 8001` 并访问对应地址。依赖下载失败时检查网络和 pip 镜像。若 `.venv` 创建中断，可将其重命名后重新启动。该服务面向本机单用户，无登录认证，请保持绑定 127.0.0.1。

## 评分与复盘

策略版本 `trend-v1`：评分使用所选日期及之前的数据，至少21期收盘价。

| 因子 | 公式（clip 限制到 0–1） | 上限 |
|---|---|---:|
| 20期动量 | 40 × clip((20期涨跌百分数 + 10) / 20) | 40 |
| 均线趋势 | 30 × clip((收盘相对20期均价的偏离百分数 + 5) / 10) | 30 |
| 稳定性 | 20 × clip(1 − 20期日收益率总体标准差百分数 / 5) | 20 |
| 流动性 | 10 × clip(20期平均成交额 / 5亿元) | 10 |

排除最新状态为 ST、停牌的样本；20期平均成交额低于1亿元、收盘价非正或非有限值、历史不足也排除。每项四舍五入后求和，同分按代码排序。阈值是演示启发式，未经回测优化，分数不代表买卖建议。

复盘保存当日全部合格样本及因子快照，以来源、日期、策略版本作为唯一键。重复生成更新快照并保留人工笔记。数据默认保存在 `data/stock.sqlite3`；停止服务后备份该文件即可。数据库和 `.env` 不提交 Git。

## 文件与 API

- `app/main.py`：服务、输入校验、日期筛选、复盘和笔记 API。
- `app/storage.py`：SQLite 表和事务；`app/providers.py`：数据源协议与模拟实现。
- `app/strategy.py`：可解释评分；`app/static/`：中文响应式网页。
- `tests/test_system.py`：接口、过滤、未来数据隔离与持久化测试。
- `docs/OPEN_SOURCE_REVIEW.md`：开源审查及选型；`docs/VALIDATION.md`：验证记录。
- `start.bat`、`requirements.txt`：Windows 启动与依赖；原有 `.github/workflows/` 运行 Windows 测试。

交互 API 文档：<http://127.0.0.1:8000/docs>。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 服务与数据库状态 |
| GET | `/api/dates` | 可选样本日期 |
| GET | `/api/screen?day=2026-10-16&limit=10` | 评分及因子 |
| POST / GET | `/api/reviews/2026-10-16` | 生成 / 读取复盘 |
| PUT | `/api/reviews/2026-10-16/notes` | 保存 `{"notes":"观察记录"}` |

测试：`.\.venv\Scripts\python.exe -m pytest -q`。

## 数据源扩展与限制

环境变量 `STOCK_DB` 可指定数据库路径；`STOCK_SOURCE` 默认 `demo`，未知来源明确报错，禁止真实行情失败后静默替换为模拟数据。新增来源需实现 `Provider.bars()`，校验数据、来源、日期及字段单位后接入；当前没有真实数据下载、重试或多源回退的已实现功能。

第一阶段不含 LLM、机器学习训练、全市场行情、真实交易日历、复权、财务时点数据、回测、手续费、涨跌停和可成交性模拟、定时任务或消息推送。后续应先完成数据质量和时点验证，再研究回测与模型；不能用本演示评价策略收益。

原创实现采用 MIT；未复制或捆绑参考项目源码。依赖保留各自许可证，详见开源审查。
