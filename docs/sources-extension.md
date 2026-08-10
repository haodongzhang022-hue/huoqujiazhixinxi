# 多源数据扩展架构 (ISSUE #5)

> 目标: 站点和获取方式会**持续增加** —— 需要一个数据源管理器, 让新增来源像「插拔」
> 一样接入, 网页预留各信息块接口, 后续需求在独立 Issue 开发。

## 1. 现状: 已纳入每日获取的数据源

| 数据源 | 适配器 | 类别 | 数据来源 | 状态 |
|---|---|---|---|---|
| CNB 开源平台新项目 | `pipeline/adapters/cnb.py` | repos | `cnb search list-public-repos` | ✅ 已实现 (真实 CLI) |
| GitHub 开源项目 | `pipeline/adapters/github.py` | repos | 包装 `pipeline.fetch` 每日快照 | ✅ 已实现 |
| arXiv 论文 | `pipeline/adapters/arxiv.py` | papers | export.arxiv.org Atom API | ✅ 已实现 (真实数据) |
| Hacker News 热点 | `pipeline/adapters/hackernews.py` | news | HN Firebase API | ✅ 已实现 (真实数据) |
| 预测市场 | `pipeline/adapters/polymarket.py` | prediction | Polymarket Gamma API | ✅ 已实现 (网络不通降级 demo) |
| RSS/Atom 订阅源 | `pipeline/adapters/rss.py` | tech/news/... | 任意 RSS (科技进展/站点更新) | ✅ 已实现 (真实数据) |

统一 **item 结构** (所有源归一化后一致):

```json
{
  "source": "arxiv",            // 数据源 id
  "item_id": "2608.00001v1",   // 来源内唯一键 (去重)
  "title": "论文标题",
  "url": "https://arxiv.org/abs/...",
  "summary": "摘要",
  "published_at": "2026-08-09T00:00:00Z",
  "category": "papers",         // repos / papers / news / tech / prediction
  "tags": ["arxiv"],
  "score": 0,                   // 热度/重要性 (越大越重要)
  "extra": { ... },             // 来源特有字段 (如 stars/成交量/概率)
  "raw": { ... }                // 原始响应 (审计)
}
```

## 2. 数据源管理器

### 2.1 三个层次

```
config/sources.json             数据源配置 (启停/参数/RSS 源列表, 热更新)
        │
pipeline/adapters/<id>.py       每个源一个 Adapter (fetch → list[item])
        │
reserve/sources.py              管理器: 列表 / 拉取调度 / 聚合摘要 digest
        │
reserve/api.py                  REST: /api/v1/sources/* + /api/v1/digest
        │
web/ (每日聚合 + 数据源管理页签)   展示
```

### 2.2 管理 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/sources` | 数据源列表 (适配器/类别/启停/缓存状态) |
| GET | `/api/v1/sources/adapters` | 适配器注册表 |
| POST | `/api/v1/sources/fetch` | 拉取全部/指定源 (body: `{"only":["cnb"]}`) |
| POST | `/api/v1/sources/enable` | 启停 (body: `{"source":"rss","enabled":false}`) |
| POST | `/api/v1/sources/config` | 更新源配置 (body: `{"source":"arxiv","config":{...}}`) |
| POST | `/api/v1/sources/feeds` | 新增 RSS 源 (body: `{"name","url","category"}`) |
| GET | `/api/v1/digest?refresh=1` | 聚合摘要 (refresh=1 强制拉最新) |

### 2.3 CLI

```bash
python -m reserve.sources --list        # 查看数据源
python -m reserve.sources --fetch       # 拉取全部启用源
python -m reserve.sources --fetch cnb   # 只拉 CNB
python -m reserve.sources --digest      # 聚合摘要
python -m reserve.sources --add-feed "站点名" "https://.../feed.xml" tech
```

## 3. 如何新增一个数据源 (3 步)

1. **写适配器** `pipeline/adapters/<id>.py`:
   ```python
   from .base import Adapter, registry

   class MyAdapter(Adapter):
       id = "myfeed"
       name = "我的站点"
       category = "tech"          # repos/papers/news/tech/prediction
       description = "..."

       def fetch(self) -> list[dict]:
           data = self.http_json("https://api.example.com/items")
           return [{"title": d["t"], "url": d["u"], "published_at": d["date"]} for d in data]

   registry.register(MyAdapter)
   ```
2. **注册配置** `config/sources.json` → `sources.myfeed` (enabled/参数)。
3. **完成** —— 页面「数据源管理」自动出现该项, 可一键拉取; 「每日聚合」自动纳入该类别。

> 适配器只需返回裸字段 (title/url/description/...), 归一化由 `base.normalize_item` 完成。

## 4. 网页预留的接口 (各信息块)

Web「每日聚合」页签按类别分块渲染, 每个块即一个信息区, 后端已预留:

| 信息块 | 后端 API | 说明 |
|---|---|---|
| 开源项目 | `/api/v1/digest` categories.repos | CNB + GitHub |
| 新论文 | categories.papers | arXiv |
| 热点信息 | categories.news | Hacker News + RSS(news) |
| 科技进展 | categories.tech | RSS(tech) / 新增源 |
| 预测市场 | categories.prediction | Polymarket (结构化行情卡片) |
| 数据源状态 | `/api/v1/digest` sources | 每源 ok/count/error |

前端 `itemCard()` 已按 `it.source` 分支渲染不同元信息
(polymarket→概率条, arxiv→作者, cnb/github→stars, hackernews→分数/评论),
新增源只需在 `itemCard()` 加一个分支即可定制卡片。

## 5. 每日定时拉取 (建议纳入 daily-fetch)

在 `.github/workflows/daily-fetch.yml` 追加一步 (可另开 Issue 做):

```yaml
- name: 多源聚合拉取
  run: |
    python -m reserve.sources --fetch || true
```

缓存 `pipeline/data/sources/*.json` 建议提交入库 (或由 CI 落盘),
页面优先读缓存, 保证离线可用。

## 6. 预测市场对接方案 (Polymarket / 期权式对冲风险平台)

> 用户提出: "类似于预测某些事物是否发生和走向, 像期权那样对冲风险的平台,
> 那里面的信息有些时候也非常重要, 但那部分怎么对接成数据信息还需要单独的开发,
> 似乎也有这样的项目从这种网页获取数据, 帮我完善"。

### 6.1 已做 (本 PR)

- **Polymarket 适配器** `pipeline/adapters/polymarket.py`:
  - 拉取活跃事件 (Gamma API, 公开无 key);
  - 归一化为 prediction 类 item, `extra` 携带: `probability_yes` / `volume` / `volume24hr` /
    `liquidity` / `end_date` / `outcome_prices`;
  - 网络不可用降级 demo 数据 (与项目既有 demo 策略一致);
- **页面预测事件卡片**: 概率条 + YES 概率 + 成交量 + 流动性 (见 `web/app.js itemCard` polymarket 分支)。

### 6.2 待专项开发 (建议另开 Issue)

| 阶段 | 内容 | 技术要点 |
|---|---|---|
| 1. 数据规范化 | 从行情 JSON 转结构化「预测事件」表 | 事件 id/问题/YES 概率/成交量/流动性/截止时间/多空分布; 存 LanceDB `prediction_events` 表 |
| 2. 历史跟踪 | 每日快照事件概率, 形成趋势 | 与 repo_snapshots 同构: 按 (event_id, date) 存概率/成交量, 供走势图 |
| 3. 信号提取 | 概率突变 / 成交量激增 / 多空比变化 | 复用 quality.py 的 delta 模型; 触发条件引擎 (trigger.py) 可加 prediction 类别 |
| 4. 关联推送 | 预测事件 ↔ 开源项目/论文关联 | 用 embedding 跨类相似检索 (reserve/search.py 已支持混合检索) |
| 5. 其他平台 | Kalshi / Manifold / 中文预测平台 | 各写一个 Adapter (30 行内), 注册即接入 |

### 6.3 同类开源项目参考 (从网页抓取预测数据的项目)

- **polymarket-api** (Python): 封装 Polymarket CLOB/Gamma API, 行情/下单;
- **py-clob-client** (Polymarket 官方): CLOB 客户端, 深度行情与订单簿;
- **manifold-api** (Python): Manifold Markets API 封装;
- **kalshi-python** (Kalshi 官方 SDK): 事件/市场/订单;
- **prediction-market-tools** (社区): 多平台行情聚合与概率走势分析。

> 这些都是「从预测网站拉数据」的现成库, 对接时可在各自 Adapter 里直接调用,
> 保持统一 item/事件 schema 即可, 无需重复造轮子。

## 7. 扩展路线图 (后续 Issue)

1. 论文源扩展: Semantic Scholar API / bioRxiv / 中文期刊;
2. 热点源扩展: Reddit / 掘金 / InfoQ / 36kr / 开源中国;
3. 科技进展: 公司技术博客 RSS 聚合 (用 --add-feed 即可);
4. 预测市场专项 (见 §6.2);
5. 每日聚合邮件/通知推送;
6. 聚合质量评估 (多源 digest 的质量分, 复用 quality.py 模型)。
