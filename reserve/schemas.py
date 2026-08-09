"""reserve/schemas.py — FastAPI 聚合管理/对外接口 的 Pydantic 数据模型。

统一「信息条目 (Item)」与「每日聚合 (DailyDigest)」的对外契约，
让人类信息流 (human) 与 AI 信息流 (ai) 共用同一份结构化数据，
只是呈现方式不同（human 分组叙述 / ai 扁平紧凑机器友好）。

预留扩展位: 后续新增「CNB 新项目 / 论文 / 热点 / 科技进展」等数据源时，
只要把各源输出归一化为 Item，即可无缝汇入每日聚合与信息流。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ItemType = Literal["repo", "paper", "trend", "news", "cnb-project"]
SourceStatus = Literal["active", "reserved", "error", "not_configured"]


class ReviewInfo(BaseModel):
    verdict: Optional[str] = None
    score: Optional[float] = None
    risks: list[str] = Field(default_factory=list)
    recommendation: Optional[str] = None


class Item(BaseModel):
    """统一信息条目（所有数据源归一化后的最小公共结构）。"""

    id: str = Field(..., description="全局唯一 id, 形如 source:inner_id")
    type: ItemType = Field("repo", description="条目类型: repo/paper/trend/news/cnb-project")
    source: str = Field(..., description="数据源 id, 如 github-repos / papers / tech-trends")
    source_label: str = Field("", description="数据源展示名, 如 GitHub 开源项目")
    title: str = Field(..., description="标题 (仓库 full_name / 论文标题 / 热点标题)")
    url: str = Field("", description="原始链接")
    description: str = Field("", description="原始描述")
    summary_zh: str = Field("", description="中文功能摘要 (人类可读)")
    language: str = Field("", description="语言 (repo 类)")
    stars: int = Field(0, description="star 数 (repo 类)")
    stars_delta_24h: Optional[int] = None
    stars_delta_7d: Optional[int] = None
    is_new: bool = Field(False, description="当周新建")
    category: str = Field("", description="生态分类")
    category_decision: str = Field("", description="action/reserve/partial/ignore")
    function_tags: list[str] = Field(default_factory=list)
    use_case: Optional[str] = None
    review: Optional[ReviewInfo] = None
    matched_needs: list[str] = Field(default_factory=list)
    published_at: str = Field("", description="发布时间 (repo 用 created_at)")
    first_seen_at: str = Field("", description="首次入库时间")
    extra: dict[str, Any] = Field(default_factory=dict, description="各数据源扩展字段")

    @property
    def content(self) -> str:
        """AI 优先信息流直接可用的正文文本。"""
        parts = [self.summary_zh or self.description or self.title]
        if self.use_case:
            parts.append(f"适用场景: {self.use_case}")
        if self.function_tags:
            parts.append("功能标签: " + ", ".join(self.function_tags))
        return "\n".join(parts)


class SourceInfo(BaseModel):
    """数据源注册信息（页面「数据源」页与 /api/v1/sources 使用）。"""

    id: str
    label: str
    description: str
    status: SourceStatus = "reserved"
    item_type: ItemType = "repo"
    enabled: bool = Field(False, description="当前是否已接入采集")
    planned: bool = Field(False, description="是否预留接口待后续开发")
    last_sync_at: Optional[str] = None
    last_items: int = Field(0, description="最近一次同步得到的条目数")
    note: str = Field("", description="状态说明 (如: 预留接口, 待接入)")


class FeedMeta(BaseModel):
    schema_version: str = Field("1.0", description="对外信息流契约版本")
    mode: Literal["human", "ai"]
    date: str
    generated_at: str
    total: int
    limit: int
    offset: int
    sources: list[str] = Field(default_factory=list)


class HumanFeedSection(BaseModel):
    key: str
    title: str
    description: str = ""
    items: list[Item] = Field(default_factory=list)


class HumanFeed(BaseModel):
    meta: FeedMeta
    headline: dict[str, Any] = Field(default_factory=dict)
    sections: list[HumanFeedSection] = Field(default_factory=list)


class AiFeed(BaseModel):
    meta: FeedMeta
    items: list[Item] = Field(default_factory=list)


class SourceSyncResult(BaseModel):
    source: str
    status: SourceStatus
    items: int = 0
    message: str = ""


class DailyDigest(BaseModel):
    """每日聚合摘要: 各数据源条目 + 汇总统计 (管理页「今日汇总」)。"""

    date: str
    generated_at: str
    stats: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceInfo] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    sections: list[HumanFeedSection] = Field(default_factory=list)


class PublicHealth(BaseModel):
    status: str = "ok"
    service: str = "reserve-fastapi"
    version: str = "1.0"
    store: str = ""
    repo_count: int = 0
    sources: list[SourceInfo] = Field(default_factory=list)
    generated_at: str = ""
