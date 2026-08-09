"""二次整理层 数据契约 (Pydantic) —— 关联边 / 矩阵 / 预测对比。

供 FastAPI 对外 API 与内部模块共用，保证输出结构稳定可消费。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ModelType = Literal["correlation", "lead_lag", "vol_spillover", "linear",
                    "momentum", "exp_decay", "var"]
VerdictType = Literal["strong", "good", "weak", "insufficient"]


class DimRef(BaseModel):
    market: str = "*"
    country: str = "*"
    exchange: str = "*"
    symbol: str = "*"
    asset: str = "*"
    timeframe: str = "*"


class RelationEdge(BaseModel):
    """一条有向边 (A→B) 的评估结果。"""

    edge: str = Field(..., description="有向边 key: A -> B")
    direction: str = Field("", description="同 edge")
    source_dim: DimRef = Field(..., description="影响源 (A)")
    target_dim: DimRef = Field(..., description="被影响方 (B)")
    model: ModelType = Field("linear", description="量化模型")
    strength: float = Field(0.0, ge=0.0, le=1.0, description="归一化影响强度 0~1")
    sign: int = Field(0, description="正/负方向: +1 / -1 / 0")
    lag: int = Field(0, description="领先滞后期数 (A 领先 B)")
    stability: float = Field(0.0, ge=0.0, le=1.0, description="滚动稳定性 0~1")
    sample_size: int = Field(0, description="有效样本数")
    params: dict[str, Any] = Field(default_factory=dict, description="模型参数")
    metrics: dict[str, Any] = Field(default_factory=dict, description="评估指标")
    insufficient_data: bool = Field(False, description="数据不足, 结果不可信")
    modeled_at: Optional[str] = None


class ComparisonCurve(BaseModel):
    dates: list[str] = Field(default_factory=list)
    actual: list[float] = Field(default_factory=list)
    predicted: list[float] = Field(default_factory=list)
    residual: list[float] = Field(default_factory=list)


class RelationComparison(BaseModel):
    """预测 vs 实际 对比 (验证预测能力)。"""

    edge: str = Field("", description="有向边 key")
    model: ModelType = Field("linear")
    train_size: int = Field(0)
    test_size: int = Field(0)
    train_dates: list[str] = Field(default_factory=list)
    test_dates: list[str] = Field(default_factory=list)
    curve: ComparisonCurve = Field(default_factory=ComparisonCurve)
    metrics: dict[str, Any] = Field(default_factory=dict, description="MAE/RMSE/MAPE/命中率/R²")
    verdict: VerdictType = Field("insufficient", description="预测能力评价")
    iterations: list[str] = Field(default_factory=list, description="后续迭代建议")
    fit: dict[str, Any] = Field(default_factory=dict)


class RelationMatrix(BaseModel):
    schema_version: str = "1.0"
    self_loops: bool = False
    dimensions: list[DimRef] = Field(default_factory=list)
    dimension_keys: list[str] = Field(default_factory=list)
    pair_count: int = Field(0)
    pairs: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: Optional[str] = None
