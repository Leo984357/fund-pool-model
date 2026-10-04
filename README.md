# Fund Pool Model

**公募基金筛选与组合研究工具：从候选基金池到评分、权重和每日 HTML 报告。**

[快速开始](#快速开始) · [输出说明](#运行后得到什么) · [配置](#常用配置) · [方法与状态](#方法与当前状态)

给定基金代码清单，程序抓取净值并存入 SQLite，计算收益、波动、回撤、Sharpe 和信息比率，再进行横截面打分与 Top-N 组合构建。适合学习和检查基金筛选流程，也适合在本地积累可复查的每日组合记录。

**当前推荐入口：命令行每日流程。** 桌面 GUI 和历史曲线模块保留为实验功能，当前状态见[方法与当前状态](#方法与当前状态)。

## 从输入到结果

```text
基金池 CSV → 净值抓取与 SQLite → 滚动指标 → 标准化评分
                                              ↓
HTML 日报 ← 评分 CSV + 组合 CSV + 数据库 ← Top-N 与三套权重
```

| 环节 | 当前实现 |
|---|---|
| 数据 | 东方财富 F10 抓取，AKShare 备用接口；本地 SQLite 存储 |
| 指标 | 年化收益、年化波动、下行波动、最大回撤、Sharpe、信息比率 |
| 打分 | 1% 缩尾、MAD 标准化、可配置因子权重；可切换为仅按 Sharpe 排序 |
| 组合 | 等权、逆波动权重、两者各占 50% 的混合权重 |
| 交付 | 每日评分表、组合权重表、HTML 报告及数据质量提示 |

## 快速开始

需要 **Python 3.10+**。以下命令在项目根目录执行；每日主流程会访问在线数据源。

```bash
git clone https://github.com/Leo984357/fund-pool-model.git
cd fund-pool-model
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install pandas numpy requests akshare lxml
```

### 1. 准备候选基金池

创建 `data/universe_fund.csv`，保留六位基金代码和列名 `fund_code`。下面是输入格式示例，可替换为自己的候选清单：

```csv
fund_code
000001
000011
000021
```

基金池不足配置上限时，程序会尝试从本地数据库和在线列表补充。若只研究 CSV 中这三只基金，请把 `FUND_UNIVERSE_LIMIT` 设为 `3`。

### 2. 运行每日流程

macOS / Linux：

```bash
FUND_UNIVERSE_LIMIT=3 \
FUND_TOP_N_FUNDS=2 \
FUND_WINDOW_DAYS=126 \
PARALLEL_WORKERS=2 \
python run_daily_fund.py
```

Windows PowerShell：

```powershell
$env:FUND_UNIVERSE_LIMIT = "3"
$env:FUND_TOP_N_FUNDS = "2"
$env:FUND_WINDOW_DAYS = "126"
$env:PARALLEL_WORKERS = "2"
python run_daily_fund.py
```

控制台会显示基金数量、评分数量、组合数量、数据提示和输出路径。首次运行会创建数据库与输出目录。若没有有效评分，先检查净值抓取日志、样本长度和基金池差异。

### 3. 查看日报与组合

用浏览器打开 `output/report.html`，查看 Top Scores 和 Portfolio Weights；用表格工具读取每日 CSV。命令行入口的实际实现见 [`run_daily_fund.py`](run_daily_fund.py) 和 [`src/pipeline/daily.py`](src/pipeline/daily.py)。

## 运行后得到什么

```text
 db/fund_db.sqlite                       # 净值与历史组合
 output/
 ├── scores_YYYY-MM-DD.csv               # 当日评分与名次
 ├── portfolio_fund_YYYY-MM-DD.csv       # 当日组合与三套权重
 └── report.html                        # 最近一次运行的日报
```

评分与组合非空时才导出对应 CSV；`report.html` 每次运行覆盖更新。日期采用本机运行日期，判断数据新鲜度时还应检查实际净值日期。

组合表的字段如下：

| 字段 | 含义 |
|---|---|
| `date`、`fund_code` | 运行日期与基金代码 |
| `score`、`rank` | 综合得分与横截面名次 |
| `weight_equal` | 等权 |
| `weight_risk_parity` | 逆波动权重；列名沿用历史命名 |
| `weight_mixed` | 50% 等权 + 50% 逆波动 |

三种方案一并导出。`weight_risk_parity` 按波动率倒数归一化，未使用完整协方差矩阵求解风险平价组合。

## 常用配置

默认值定义在 [`src/_config.py`](src/_config.py)，在启动 Python 前设置环境变量。

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `FUND_DATA_DIR` | 项目下 `data/` | 基金池目录，默认读取其中的 `universe_fund.csv` |
| `FUND_DB_PATH` | `db/fund_db.sqlite` | SQLite 文件 |
| `FUND_OUTPUT_DIR` | `output/` | 评分、组合与日报目录 |
| `FUND_UNIVERSE_LIMIT` | `100` | 候选基金池上限 |
| `FUND_TOP_N_FUNDS` | `3` | 选取基金数量 |
| `FUND_WINDOW_DAYS` | `252` | 因子回看窗口 |
| `FUND_SINCE_DATE` | `2022-01-01` | 净值筛选起始日期 |
| `PARALLEL_WORKERS` | `10` | 抓取并发数 |
| `FUND_PURE_SHARPE_ONLY` | `false` | 仅使用 Sharpe 打分 |
| `FW_ann_return` 等 `FW_指标名` | 见配置文件 | 对应因子的评分权重 |

当前 `Config` 通过 `FUND_DATA_DIR` 确定默认基金池路径；旧版文档中的 `FUND_UNIVERSE_CSV` 未接入此命令行配置。自定义文件名可在 Python 中构造 `Config(universe_csv="路径")` 后调用 `run_daily(config)`。

## 方法与当前状态

- **指标口径：** 年化收益使用日均收益乘以 252，Sharpe 未扣除无风险收益；IR 的基准是当前基金池等权日收益。有效样本阈值由因子函数按窗口计算。
- **净值口径：** 当前收益由单位净值变化计算；分红、份额拆分等事件需要额外校验，才能解释为投资者总回报。
- **评分检查：** CSV 内的因子列是标准化后的评分输入。当前最大回撤使用负数表示，调整回撤权重前应核对符号方向。
- **历史曲线：** [`src/backtest/engine.py`](src/backtest/engine.py) 使用数据库中已有的组合日期生成曲线，尚需核对交易日对齐、费用和调仓假设。每日流程只生成筛选结果与日报，不自动重建严格的历史选基回测。
- **桌面界面：** 安装 `PySide6 matplotlib` 后可用 `python -m gui.app` 打开；部分后台流程仍引用重构前模块，完整 GUI 流程待适配。

## 代码导航

| 路径 | 职责 |
|---|---|
| [`src/data/`](src/data/) | 基金池、抓取、SQLite 读写与收益转换 |
| [`src/domain/`](src/domain/) | 因子、评分、权重与数据质量提示 |
| [`src/pipeline/`](src/pipeline/) | 每日与增量处理流程 |
| [`src/reporting/`](src/reporting/) | HTML 日报与绘图 |
| [`src/backtest/`](src/backtest/) | 历史组合曲线与回填实验 |
| [`gui/`](gui/) | PySide6 桌面界面 |

后续重点：统一 GUI 与当前数据管线、校准净值和回撤口径，并补齐可复核的历史调仓评估。
