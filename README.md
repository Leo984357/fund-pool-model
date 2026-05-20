程序从AKShare 接东方财富/天天基金历史净值接口，写入SQLite数据库读取并增量抓取基金历史净值，计算窗口内因子，做横截面打分，选出得分最高的若干只基金（默认 10 只），按等权、逆波动、混合三种方案配权，结果写回数据库并导出 CSV。提供命令行脚本与 GUI 两种使用方式。构建公募基金池并进行日度选基与组合权重生成。

管线流程

基金池准备（抓取基金列表）：优先读取 data/universe_fund.csv；若数量不足，会从本地数据库补齐，仍不足再尝试在线来源（AKShare）获取候选并落到 CSV。最终截断至上限。
抓取时间序列净值列表：若抓取模块可用，按自定义 since 日期→今日抓取日度净值，写入 db/fund_db.sqlite 的 fund_nav_daily 表（幂等写入，主键为 fund_code+date）。抓取异常不阻断后续流程。
读库与预处理：从 fund_nav_daily 读取入池基金的净值序列，转换为日收益，过滤历史不足的代码。
因子计算与标准化：基于窗口天数计算年化收益、年化波动、下行波动、Sharpe、信息比率、最大回撤等；做异常值裁剪与标准化。
打分与排序：按权重线性合成综合分，或配置为仅用 Sharpe 排序；对得分表降序排序并生成 rank。
选基与配权：选取前 Top-N 只基金，计算三套权重（等权、逆波动、混合），得到当日持仓。
入库与导出：将当日结果写入 portfolio_results 表，并导出 output/portfolio_fund_YYYY-MM-DD.csv 与 output/scores_YYYY-MM-DD.csv。
可选回测与报告：按当日权重与历史净值生成回测净值曲线，导出 output/equity_curve.csv；GUI 中展示运行日志与结果预览。

部署需求
操作系统：Windows、macOS 或 Linux
Python：3.9 及以上（推荐 3.10）
依赖库：pandas、numpy、requests、akshare、python-dateutil、pytz；使用 GUI 需要 PySide6；可选绘图 matplotlib
数据库：内置 sqlite3（Python 标准库），无需安装额外服务
网络：如需在线抓取，需要可访问相关数据源的网络环境；无法联网时也可仅用本地库计算

# 依赖与环境 bash 可直接执行
python -m venv .venv && \
source .venv/bin/activate || source .venv/Scripts/activate && \
pip install -U pip && \
pip install pandas>=2.0 numpy>=1.24 requests>=2.31 akshare>=1.11.0 \
            python-dateutil>=2.8 pytz>=2023.3 PySide6>=6.5 matplotlib>=3.7


安装步骤

创建环境并安装依赖
python -m venv .venv 或 conda create -n fund python=3.10
激活环境后执行 pip install -r requirements.txt
若没有 requirements.txt，可执行 pip install pandas numpy requests akshare PySide6 python-dateutil pytz
首次运行会自动创建 db/fund_db.sqlite、output/ 等目录。国内网络环境如安装或抓取较慢，可配置镜像或代理。

使用方法
方式一（GUI）

进入项目根目录，执行 python gui/app.py
在界面选择起始日期、Top-N、窗口天数、基金池上限、权重方案、并行 workers，并指向基金池 CSV（默认为 data/universe_fund.csv）
点击“开始”，在“监控台”查看日志；完成后在“组合与交易”“结果总览”等页查看 Top-N 与交易清单；导出的 CSV 在 output/ 目录

方式二（命令行）

日常主流程 python run_daily_fund.py
会完成（可选抓取）→读库→因子→打分→选基→配权→入库+导出，并在控制台输出日志

回测（不稳定，我还在调试） python run_backtest_fund.py
生成 output/equity_curve.csv 等结果
如需初始化或重置数据库，可删除 db/fund_db.sqlite 或按你们仓内的 init/reset 脚本使用

# Fund_pool_model 目录导图
.
├── data/                                   # 基金池 CSV
│   └── universe_fund.csv                   # 手工/自动维护的候选基金清单
├── db/                                     # 本地数据库
│   └── fund_db.sqlite                      # SQLite（程序自动创建/更新）
├── output/                                 # 每日输出物
│   ├── portfolio_fund_YYYY-MM-DD.csv       # 当日组合（三套权重、score、rank）
│   └── scores_YYYY-MM-DD.csv               # 当日打分明细
├── gui/                                     # 图形界面
│   ├── app.py                              # GUI 入口
│   ├── view_from_output.py                 # 直接从 output 渲染结果页
│   └── widgets/
│       ├── MainWindow.py                   # 主窗口/页签与事件
│       ├── RunTable.py                     # DataFrame → QTableView 渲染
│       └── __init__.py
├── src/                                     # 业务与管线
│   ├── config.py                           # 全局配置/路径/ENV 读取
│   ├── dao.py                              # SQLite 工具（建表/UPSERT/查询）
│   ├── universe_fund.py                    # 基金池生成/兜底/去重/截断
│   ├── data_fetcher_ak_fund.py             # 在线抓取（东财F10优先，AKShare兜底）
│   ├── parallel_fetch.py                   # 并行抓取调度（progress 回调）
│   ├── data_loader_fund.py                 # 读库与“净值→收益”，样本过滤
│   ├── feature_engineering_fund.py         # 因子计算（收益/波动/回撤/Sharpe/IR）
│   ├── scoring_model.py                    # 标准化与综合打分，生成 rank
│   ├── optimizer.py                        # 选 Top-N 与配权（等权/逆波动/混合）+ 导出
│   ├── backfill_portfolio.py               # 静态权重兜底曲线
│   ├── backtest_quick_fund.py              # 快速回测产曲线
│   ├── reporting.py                        # 日报/摘要（可选）
│   └── plotting.py                         # 绘图组件（可选）
├── run_daily_fund.py                        # 每日主流程入口（CLI）
├── init_db.py                               # 初始化建表
├── reset_db.py                              # 重置/清空数据库
└── README.md                                # 自述文档


配置说明
所有默认配置在 src/config.py，可用环境变量覆盖。常用项如下：
FUND_DB_PATH 本地 SQLite 路径，默认项目根/db/fund_db.sqlite
FUND_OUTPUT_DIR 输出目录，默认项目根/output
FUND_UNIVERSE_CSV 基金池 CSV 路径，默认项目根/data/universe_fund.csv
FUND_UNIVERSE_LIMIT 基金池上限（筛选截断）
FUND_TOP_N_FUNDS 每日选取只数（Top-N）
FUND_WINDOW_DAYS 因子窗口天数（如 126 或 252）
FUND_SINCE_DATE 抓取起始日期（首次或回补）
FUND_MIN_HISTORY_DAYS 入池最小历史天数过滤
FUND_WEIGHT_SCHEME 展示权重方案（weight_equal / weight_risk_parity / weight_mixed）
PARALLEL_WORKERS 并行抓取与计算的并发数
FACTOR 权重 可在环境变量或配置中调整各因子权重；设置仅 Sharpe 排序时忽略其它权重


数据库与表结构
db/fund_db.sqlite
fund_nav_daily(fund_code TEXT, date TEXT, nav REAL)，主键（fund_code, date）
portfolio_results(date TEXT, fund_code TEXT, weight_equal REAL, weight_risk_parity REAL, weight_mixed REAL, score REAL, rank INTEGER)，主键（date, fund_code）


输出说明
output/portfolio_fund_YYYY-MM-DD.csv 当日持仓与三套权重、分数与名次
output/scores_YYYY-MM-DD.csv 当日横截面打分明细（若非空则导出）
output/equity_curve.csv 回测或快速评估生成的净值曲线
GUI 若启用了 artifacts 目录，也会在 gui/artifacts 下生成一次性快照文件


常见使用提示

首次跑通建议先准备小规模基金池（比如 10 只）验证；待流程稳定后再放大到几百或上千，并调整并发数以匹配网络与 CPU
Top-N 与基金池上限的关系：先在池内按得分排序取前 N；若入池基金不足，将按实际数量返回



一键最小流程示例

准备 data/universe_fund.csv（若没有也可直接运行，程序会尝试补齐）
运行 GUI：python gui/app.py，选择 Top-N、窗口天数等参数，点击开始
或
运行 CLI：python run_daily_fund.py
查看 output/portfolio_fund_当天日期.csv 和 scores_当天日期.csv，确认权重与名次符合预期
如需回测：python run_backtest_fund.py，查看 output/equity_curve.csv