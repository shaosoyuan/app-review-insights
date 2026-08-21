"""
Data models for App Review Insights.
"""
from pydantic import BaseModel, Field
from typing import Optional


class Review(BaseModel):
    """A single App Store review."""
    review_id: str
    author: str
    rating: int
    title: str
    content: str
    version: Optional[str] = None
    date: Optional[str] = None


class CleanedReview(BaseModel):
    """A review after cleaning and deduplication."""
    review_id: str
    author: str
    rating: int
    title: str
    content: str
    version: Optional[str] = None
    date: Optional[str] = None
    content_length: int = 0
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None
    language: str = "en"


class Finding(BaseModel):
    """A product finding derived from review analysis."""
    finding_id: str
    category: str
    summary: str
    severity: str  # critical, high, medium, low
    source_review_ids: list[str] = Field(default_factory=list)
    source_excerpts: list[str] = Field(default_factory=list)
    sample_count: int = 0
    confidence: float = 0.0
    uncertainty: str = ""
    conflicting_evidence: Optional[str] = None
    is_model_generated: bool = True


class Requirement(BaseModel):
    """A product requirement derived from findings."""
    req_id: str
    title: str
    description: str
    priority: str  # P0, P1, P2
    source_finding_ids: list[str] = Field(default_factory=list)
    source_review_ids: list[str] = Field(default_factory=list)
    version: str = "v1.0"


class TestCase(BaseModel):
    """A test case linked to a requirement."""
    test_id: str
    title: str
    description: str
    steps: list[str] = Field(default_factory=list)
    expected_result: str
    requirement_id: str
    source_review_ids: list[str] = Field(default_factory=list)


class PRDDraft(BaseModel):
    """A Product Requirements Document draft."""
    title: str
    overview: str
    target_audience: str
    requirements: list[Requirement] = Field(default_factory=list)
    version_plan: list[dict] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Complete analysis result."""
    model_config = {"protected_namespaces": ()}

    app_name: str = ""
    app_id: str = ""
    analysis_goal: str = ""
    total_reviews_collected: int = 0
    total_reviews_after_cleaning: int = 0
    reviews: list[Review] = Field(default_factory=list)
    cleaned_reviews: list[CleanedReview] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    prd: Optional[PRDDraft] = None
    test_cases: list[TestCase] = Field(default_factory=list)
    traceability_matrix: list[dict] = Field(default_factory=list)
    data_limitations: str = ""
    model_info: dict = Field(default_factory=dict)
    timestamp: str = ""
