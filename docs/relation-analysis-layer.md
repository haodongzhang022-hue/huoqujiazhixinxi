# 二次整理层 · 金融各市场两两关联量化（ISSUE #7）

> 数据获取层（ISSUE #6，另一专项）负责把全球金融数据按
> **国家 → 交易所 → 品种 → 交易类型 → 时间级别** 组织成「小目录」并提供获取能力；
> 本层（`reserve/relations/`）处理的是**有了数据之后**的事：
> 这些不同小目录之间的**两两互相影响**——评估、量化、建模、并验证预测能力。

---

## 0. 核心设计哲学（对齐 ISSUE 原文）

| 需求原文 | 本层落点 |
|---|---|
| 这不是一种影响，是**两两需要评估** | 关联是**有向边**：A→B 与 B→A 是两条独立边，各自建模、各自验证（`ordered_pairs` 全笛卡尔积，排除自环） |
| 跨市场 / 跨国家 / 跨品种 / 跨时间周期 | 维度系统 `market.country.exchange.symbol.asset.timeframe` 全覆盖，任意子集可两两组合 |
| 同市场下的品种也互相评估 / 同品种不同交易类型、不同时间级别 | 维度天然支持：`000300.index ↔ 000300.etf`（同品种不同交易类型）、`BTC.1d ↔ BTC.4h`（跨时间级别）等都会进入矩阵 |
| 量化这种关联，可以是**固定值，但大多数时候可能是变量，甚至需要一个模型去拟合** | 7 种模型：`correlation`（固定值）→ `lead_lag` / `vol_spillover`（时变领先/波动溢出）→ `linear` / `momentum` / `exp_decay`（回归拟合）→ `var`（向量自回归 + 格兰杰式检验） |
| 需要描述模型预测出来的互相影响，和**实际的影响的曲线**，放一起对比 | `compare` 模块：滚动回测（训练段拟合 → 测试段预测 vs 实际），输出双曲线 + MAE/RMSE/MAPE/方向命中率/R² |
| 这样才能表现我们**预测能力到底够不够**，这影响到后续的迭代 | 每条边给出 `verdict: strong / good / weak / insufficient` + 可执行的**迭代建议**（加样本、换模型、引入宏观因子、降预测窗口…） |

---

## 1. 模块结构

```
reserve/relations/
├── __init__.py    包说明
├── dims.py        维度定义与解析（市场/国家/交易所/品种/交易类型/时间级别 -> 目录 key）
├── frame.py       矩阵定义：目标集 -> 全两两有序边（排除自环、方向敏感）
├── engine.py      关联评估引擎：11 种量化模型（固定值/时变/回归/VAR/结构突变/事件研究/自相关）
├── compare.py     预测 vs 实际 曲线对比 + 误差统计 + verdict 评价 + 多模型自动择优
├── network.py     传导网络分析：节点中心性 / 强关联簇 / 传导路径（矩阵之上的全局视角）
├── store.py       关联矩阵持久化（relation_store/，JSON，兼容 LanceDB 预留）+ 序列快照
├── schemas.py     Pydantic 数据契约（对外 API 稳定输出）
└── demo.py        内置演示数据 + 端到端演示（python -m reserve.relations.demo）
```

数据流：

```
数据获取层面板 {dim_key: {date: value}}
        │  (跨时间级别自动重采样对齐)
        ▼
build_matrix ──► 全两两有向边 (8 维 -> 56 条)
        │
        ▼
evaluate_pair ──► strength / sign / lag / stability / model / params
        │
        ▼
compare (滚动回测) ──► 预测曲线 vs 实际曲线 + 指标 + verdict + 迭代建议
        │
        ▼
RelationStore 落盘 ──► FastAPI /api/v1/relations/* ──► Web「关联分析」页
```

---

## 2. 维度系统（`dims.py`）

```
market.country.exchange.symbol.asset.timeframe
   ↓        ↓         ↓        ↓       ↓        ↓
 期货       CN       SHFE      CU     合约     日线
```

- 字符串解析：`"futures.CN.SHFE.CU.futures.1d"` 全 6 段；`"futures.CU"` 短格式自动映射
  （market=futures, symbol=CU）；缺省段补 `*`
- `Dim.matches()`：通配符匹配，用于目录归属判断
- 覆盖示例：
  - 跨市场：`equity.* ↔ futures.* ↔ forex.* ↔ crypto.* ↔ macro.*`
  - 跨国家：`CN.* ↔ US.* ↔ JP.* ↔ HK.*`
  - 同市场跨品种：`CU ↔ GC ↔ rb`（同为期货）
  - 同品种不同交易类型：`000300.index ↔ 000300.etf ↔ 000300.futures`
  - 同品种不同时间级别：`BTC.1d ↔ BTC.4h ↔ BTC.1h`

### 2.1 功能域分层漏斗（LAYERS）

维度不是平铺的 6 个并列字段，而是**一个多级条件筛选的漏斗**。每一级是一个**功能域 (functional domain)**，有明确的漏斗深度（顶层最粗 → 底层最细）：

```
L0  资产大类/功能域 (data_class / market)   ← 漏斗口（最粗）
L1  地区/国家       (region / country)
L2  交易所/市场     (exchange)
L3  品种/标的       (instrument / symbol)
L4  交易类型        (trade_type / asset)
L5  时间级别        (time_level / timeframe) ← 漏斗底（最细）
```

- `LAYERS` 定义了这 6 层及其 `order`（0=顶层）。
- `Dim.active_layers()` / `Dim.path()` / `Dim.funnel_label()`：把维度展开成**漏斗路径**，如 `资产大类:futures → 地区:CN → 交易所:SHFE → 品种:CU → 交易类型:futures → 时间级别:1d`。
- `relationship_kind(A, B)`：判定两维度是**层内**还是**层间**关系：
  - **层内 intra_layer**：两个维度属于**同一个最顶层功能域**（资产大类相同），仅在最细分/子分类层不同，如 `000300.index ↔ 000300.etf`、`BTC.4h ↔ BTC.1d`。模型学的是「同一功能域分支内部的联动」。
  - **层间 inter_layer**：两个维度属于**不同的最顶层功能域**（如股票 ↔ 期货、宏观 ↔ 加密），跨功能域传导，如美债利率 → 股票。模型学的是「跨功能域的层间传导」。

> ⚠️ 为什么必须分层？后续模型要**分别学习层内关系与层间关系**。若把 6 维拍平成同一个 key，层内/层间就混在一起无法区分。分层后网络拓扑才能按功能域渲染成漏斗、边才能带 `intra_layer / inter_layer` 标记，为「层内模型 + 层间模型」预留结构。

---

## 3. 评估引擎（`engine.py`）

所有模型都是**方向敏感**的（A→B 与 B→A 计算时 A/B 互换、滞后方向互换），且
**统一在收益率空间拟合**（消除价格量纲差异，弹性系数可跨品种比较）：

| 模型 | 含义 | strength 依据 |
|---|---|---|
| `correlation` | 固定值型：Pearson 相关系数 | \|corr\| |
| `lead_lag` | 扫描 ±max_lag 找最大 \|corr\| 的领先滞后 | 最大 \|corr\| |
| `vol_spillover` | 波动溢出：A 的波动（\|收益\|）对 B 波动的影响 | 波动相关 |
| `linear` | B = a + b·A(t-lag) | 收益率 R² |
| `momentum` | B_t = a + b·A(t-1) + c·B(t-1)（扩散+自身动量） | R² |
| `exp_decay` | 指数衰减加权回归（近因效应） | R² |
| `var` | 双变量 VAR(1)，格兰杰式增量 R² 检验 | 增量 R² + 弹性 |
| `rolling_corr` | **时变相关**：滚动窗口相关曲线，回答"关联大多数时候是变量" | 均相关+趋势 |
| `regime_shift` | **结构突变**：前后段相关对比，检出 strengthen/weaken/reverse/appear/disappear | 后段相关+突变 |
| `event_study` | **事件研究**：A 异常波动后 B 的窗口反应 + 命中率 | 平均反应+命中率 |
| `self_corr` | **自相关**：B 自身动量/均值回归（识别"自己影响自己"） | 最强自相关 |

输出统一字段：`edge / direction / model / strength(0~1) / sign(±1) / lag / stability(0~1) / sample_size / params / metrics / insufficient_data / modeled_at`

> 💡 **第二轮完善**：`rolling_corr`（时变关联曲线）直接对齐 ISSUE 原文"大多数时候可能是变量"；
> `regime_shift`（结构突变）回答"关系是否随时间切换"；`event_study`（事件研究）回答"A 发生大事时 B 怎么反应"；
> `self_corr`（自相关）补上"自己影响自己"的评估。

---

## 4. 预测能力验证（`compare.py`）—— 回答“够不够”

滚动回测流程：

1. **训练段**（前 70%）拟合模型参数
2. **测试段**（后 30%）用训练参数做逐点预测，得到 `predicted` 曲线
3. 与 `actual` 曲线逐点对比，输出：
   - `curve`：`{dates, actual, predicted, residual}`（前端 Canvas 双曲线图）
   - 指标：`mae / rmse / mape / hit_rate(方向命中率) / r2 / correlation / nrmse`
4. 评价分级：

| verdict | 判据 | 含义 |
|---|---|---|
| `strong` | R²≥0.5 且 hit≥0.65 | 预测能力强，可进入策略/自动化触发 |
| `good` | R²≥0.3 或 hit≥0.6 | 有可用信号，进观察名单 |
| `weak` | R²>0.05 或 hit>0.52 | 信号偏弱，进迭代队列 |
| `insufficient` | 其余 | 无预测能力，标记低置信边 |

每条边附带 `iterations`（具体迭代建议：增加样本 / 换模型 / 引入宏观因子 / 缩短预测窗口 / 细分时间级别…）。

### 4.1 多模型自动择优（`compare_models`）—— 回答“换模型能不能更好”

`compare_models(series_a, series_b)` 自动试跑 linear / momentum / exp_decay / var / correlation
五种模型，按测试段综合得分 `score = r2*0.5 + hit_rate*0.3 + (1-nrmse)*0.2` 排序，返回
`{best, ranking, comparisons}`：

- `best`：预测能力最优的模型及其曲线（可覆盖默认模型结果）
- `ranking`：各模型得分/verdict 排行（前端表格展示“换模型”的收益）
- 直接响应 ISSUE 迭代建议中的“换模型”，无需人工反复试参

---

## 5. 传导网络（`network.py`）—— 矩阵之上的全局视角

单条边回答“A 对 B 的影响”，网络回答“**整个市场怎么联动**”：

| 能力 | 说明 |
|---|---|
| 节点中心性 | 每个维度的出强度/入强度/总强度 + hub(影响源)/authority(被影响) 归一化评分 |
| 强关联簇 | 双向强连接节点归簇（社团发现），识别“哪些品种抱团联动” |
| 传导路径 | 源→目标的强传导链路（边强度乘积排序），识别“风险/信息沿什么路径传导” |
| 分层漏斗 | 按**功能域层**归组节点（资产大类/地区/…），区分**层内边**（同功能域分支内联动）与**层间边**（跨功能域传导），供漏斗式拓扑渲染 |
| 网络摘要 | 节点数/边数/密度/最大簇/最强枢纽/最强边 + **层内/层间边数**，供页面卡片与 API 直接消费 |

典型输出（演示数据）：
```
🕸️ 分层漏斗·传导网络: 7 节点 · 18 边 · 层内4 · 层间14
🧭 最强枢纽(影响源): macro...US10Y (利率是全局领先驱动)
🎯 最强权威(被影响): equity...000300 (权益被宏观/汇率/风险偏好共同驱动)
💠 最大联动簇: 000300 指数 + 000300 ETF (层内·同品种不同交易类型)
📌 功能域分层: 资产大类 → 地区 → 交易所 → 品种 → 交易类型 → 时间级别
```

边列表 API 支持 `?rel=intra_layer|inter_layer` **多级漏斗筛选**，配合页面下拉即可
只查看「层内(同功能域)联动」或「层间(跨功能域)传导」。

---

## 6. 持久化（`store.py`）

```
relation_store/
├── matrix.json          # 矩阵骨架（维度 + 两两有序边清单）
├── edges/<edge>.json    # 每条边的评估结果（edge = "A -> B" 安全转义）
├── comparisons/<edge>.json  # 每条边的预测 vs 实际对比
├── series/<dim>.json    # 各维度序列快照（供前端/API 实时多模型对比）
└── meta.json            # 更新时间/统计
```

- 环境变量 `RELATION_DIR` 可指定目录（默认仓库根 `relation_store/`，已加入 `.gitignore`）
- 预留 LanceDB 表结构迁移位（边即二维表：from_key/to_key/model/strength/sign/lag/stability/verdict）

---

## 7. API 与页面

FastAPI 新增 `/api/v1/relations/*` 一组端点（tag: 二次整理层）：

| 端点 | 说明 |
|---|---|
| `GET /api/v1/relations/matrix` | 矩阵骨架（维度 + 两两有序边） |
| `GET /api/v1/relations/edges` | 关联边列表（过滤 min_strength/model/verdict，排序） |
| `GET /api/v1/relations/edge/{edge}` | 单边详情（评估 + 预测对比 + 时变曲线数据） |
| `GET /api/v1/relations/comparisons` | 预测能力对比列表（按 R² 排序） |
| `POST /api/v1/relations/evaluate` | 实时评估两条序列（A→B） |
| `POST /api/v1/relations/compare` | 实时滚动回测（预测 vs 实际） |
| `POST /api/v1/relations/run-demo` | 一键运行内置演示（8 维 → 56 条边） |
| `GET /api/v1/relations/network` | **传导网络**：节点中心性 + 强关联簇 + 摘要 |
| `GET /api/v1/relations/paths` | **传导路径**：源→目标强链路 |
| `POST /api/v1/relations/compare-models` | **多模型自动择优**（换模型迭代） |
| `POST /api/v1/relations/auto-model` | 批量/调度用：对序列对自动选最优模型 |

Web 管理台「**关联分析**」页签：
- 预测能力分布统计卡（strong/good/weak/insufficient）
- **传导网络图**（Canvas）：节点大小=影响强度，连线=关联边，附枢纽/权威/联动簇摘要
- 两两关联边表格（强度条 / 方向 / 领先 / 稳定性 / 模型 / 测试段 R²·命中率 / 评价），支持按模型筛选
- 点击任意边 → **Canvas 双曲线图**：蓝=实际影响曲线，橙虚线=模型预测影响曲线，附 R²/命中率/RMSE/MAE 与迭代建议
- **时变关联强度曲线**（rolling_corr）：绿/红线展示关联强度随时间波动
- **多模型择优表**：同一对序列试跑 5 种模型，展示最优模型与各模型得分

---

## 8. 演示（`demo.py`）

```bash
python -m reserve.relations.demo --days 200 --model linear --max-lag 8
python -m reserve.relations.demo --model rolling_corr   # 时变关联视角
python -m reserve.relations.demo --model regime_shift   # 结构突变视角
python -m reserve.relations.demo --compare-models       # 输出每条边最优模型
```

内置 8 个维度 × 合成数据（含可验证的真实传导结构）：
US10Y 宏观领先影响权益/铜/黄金/汇率（收益率级传导）、BTC→AAPL 风险偏好联动、
000300 指数↔ETF 高度同步（同品种不同交易类型）、USDCNY→A股 负相关、BTC 4h 跨时间级别自动重采样对齐。

演示验证（`tests/test_relations.py::test_demo_summary_recovers_structure`）：
引擎能还原出「000300 指数 ↔ 000300 ETF」为最强关联边，且 56 条边全部产出预测能力评价，
并额外输出传导网络（枢纽/权威/联动簇）。

---

## 9. 与数据获取层（ISSUE #6）的对接方式

数据获取层落地后，只需把面板数据归一化为 `{dim_key: {date: value}}`：

```python
from reserve.relations.engine import evaluate_all
from reserve.relations.frame import build_matrix

panel = load_finance_panel()          # 数据获取层产出
matrix = build_matrix(list(panel))    # 自动生成全两两有序边
results = evaluate_all(panel, model="linear")   # 全量两两评估
for r in results:
    store.save_edge(r)
    cmp = compare(panel[a_key], panel[b_key], model="linear")
    store.save_comparison(r["edge"], cmp)
```

更复杂的情况（神经网络 / 因子模型 / 多变量 VAR-p / 事件研究法）可在 `engine.py`
的 `MODELS` 中注册新模型，输出契约不变，页面/API 无需改动。
