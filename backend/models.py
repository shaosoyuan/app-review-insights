"""Data models for the review analysis pipeline."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class Review(BaseModel):
    """A single App Store review."""
    id: str
    author: str = ""
    rating: int = 0
    title: str = ""
    body: str = ""
    version: str = ""
    updated: Optional[str] = None
    # cleaned fields
    cleaned_body: str = ""
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None
    language: str = "en"


class Finding(BaseModel):
    """A product finding derived from review analysis."""
    id: str
    summary: str
    category: str
    severity: str = "medium"  # high, medium, low
    source_review_ids: list[str] = Field(default_factory=list)
    source_excerpts: list[str] = Field(default_factory=list)
    sample_count: int = 0
    confidence: float = 0.0  # 0.0 - 1.0
    conflicting_evidence: list[str] = Field(default_factory=list)
    is_model_generated: bool = True
    analysis_type: str = "semantic"  # semantic or statistical


class Requirement(BaseModel):
    """A product requirement derived from findings."""
    id: str
    title: str
    description: str
    priority: str = "P2"  # P0, P1, P2, P3
    target_version: str = "v1.0"
    source_finding_ids: list[str] = Field(default_factory=list)
    source_review_ids: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    """A test case linked to a requirement."""
    id: str
    title: str
    requirement_id: str
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    source_review_ids: list[str] = Field(default_factory=list)
    source_review_excerpts: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Complete analysis result containing all pipeline outputs."""
    model_config = ConfigDict(protected_namespaces=())

    job_id: str = ""
    app_info: dict = Field(default_factory=dict)
    total_reviews: int = 0
    duplicates_removed: int = 0
    rating_distribution: dict = Field(default_factory=dict)
    version_distribution: dict = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    version_plan: dict = Field(default_factory=dict)
    traceability_report: dict = Field(default_factory=dict)
    model_info: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
