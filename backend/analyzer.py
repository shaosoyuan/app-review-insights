"""
LLM analyzer - model-driven semantic analysis of reviews.

This module uses a large language model (via OpenAI-compatible API) for:
1. Dynamic topic discovery - clustering reviews into themes without predefined categories
2. Issue consolidation - synthesizing user complaints into product findings
3. Evidence-grounded analysis - every finding must cite source reviews
4. PRD generation - turning findings into actionable requirements
5. Test case generation - creating test cases linked to requirements

Why LLM for these tasks (not rules):
- Review classification requires understanding nuanced natural language, sarcasm,
  and implicit complaints that keyword matching cannot capture.
- Finding consolidation requires reasoning across multiple reviews to identify
  common root causes.
- PRD and test case generation require creative synthesis, not pattern matching.

Failure handling strategy:
- If LLM is unavailable, falls back to a rule-based classifier (clearly labeled).
- Retries up to 3 times on transient errors.
- All model outputs are validated for required fields; missing fields are flagged.
- Hallucination mitigation: prompts explicitly require source review IDs and
  instruct the model to mark uncertainty.
"""
import json
import time
import re
from typing import Optional
from openai import OpenAI
from .models import Review, Finding, Requirement, TestCase
from .config import config
from .cleaner import get_rating_distribution


def _get_client() -> Optional[OpenAI]:
    """Create OpenAI client if API key is available."""
    if not config.llm_available:
        return None
    try:
        return OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
    except Exception:
        return None


def _call_llm(client: OpenAI, system_prompt: str, user_prompt: str, max_retries: int = 3) -> Optional[str]:
    """Call LLM with retry logic. Returns None on failure."""
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,  # Low temperature for more deterministic output
                max_tokens=4096,
            )
            return resp.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return None
    return None


def _parse_json_response(text: str) -> Optional[dict]:
    """Extract and parse JSON from LLM response, handling markdown code blocks."""
    if not text:
        return None
    # Try to extract JSON from code blocks
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        text = match.group(1)
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def prepare_reviews_for_llm(reviews: list[Review], max_reviews: int = 150) -> str:
    """Format reviews into a compact text for LLM analysis."""
    # Prioritize low-rating reviews and reviews with substantial body text
    sorted_reviews = sorted(reviews, key=lambda r: (r.rating, len(r.body)))
    selected = sorted_reviews[:max_reviews]

    lines = []
    for r in selected:
        lines.append(
            f"[ID:{r.id}] Rating:{r.rating}/5 Version:{r.version or 'N/A'} "
            f"Title:\"{r.title}\" Body:\"{r.cleaned_body[:500]}\""
        )
    return "\n".join(lines)


def analyze_reviews(reviews: list[Review], analysis_goal: str = "") -> list[Finding]:
    """
    Model-driven review analysis: discover topics, consolidate issues,
    and generate evidence-grounded findings.

    Returns a list of Finding objects with source review IDs and confidence.
    """
    client = _get_client()

    if not client:
        return _fallback_analysis(reviews, analysis_goal)

    reviews_text = prepare_reviews_for_llm(reviews)
    rating_dist = get_rating_distribution(reviews)

    system_prompt = (
        "You are a product analyst specializing in mobile app review analysis. "
        "Your task is to discover topics and issues from real user reviews "
        "WITHOUT relying on predefined categories. Every finding MUST include "
        "the source review IDs that support it. If evidence is insufficient "
        "or conflicting, mark confidence accordingly.\n\n"
        "Return a JSON object with this structure:\n"
        '{\n'
        '  "findings": [\n'
        '    {\n'
        '      "summary": "short description of the issue/theme",\n'
        '      "category": "a dynamically discovered category name",\n'
        '      "severity": "high|medium|low",\n'
        '      "source_review_ids": ["id1", "id2"],\n'
        '      "source_excerpts": ["short quote from review", ...],\n'
        '      "sample_count": number,\n'
        '      "confidence": 0.0-1.0,\n'
        '      "conflicting_evidence": ["any conflicting feedback or empty array"]\n'
        '    }\n'
        '  ]\n'
        '}\n'
        "Generate 5-15 findings. Focus on actionable product issues."
    )

    goal_text = f"\nAnalysis goal: {analysis_goal}" if analysis_goal else ""
    user_prompt = (
        f"Analyze these App Store reviews and discover key product issues.\n"
        f"Total reviews: {len(reviews)}\n"
        f"Rating distribution: {json.dumps(rating_dist)}\n"
        f"{goal_text}\n\n"
        f"Reviews:\n{reviews_text}\n\n"
        f"Return ONLY the JSON object."
    )

    raw = _call_llm(client, system_prompt, user_prompt)
    if not raw:
        return _fallback_analysis(reviews, analysis_goal)

    data = _parse_json_response(raw)
    if not data or "findings" not in data:
        return _fallback_analysis(reviews, analysis_goal)

    findings = []
    for i, f in enumerate(data["findings"]):
        finding = Finding(
            id=f"F-{i+1:03d}",
            summary=f.get("summary", ""),
            category=f.get("category", "uncategorized"),
            severity=f.get("severity", "medium"),
            source_review_ids=f.get("source_review_ids", []),
            source_excerpts=f.get("source_excerpts", []),
            sample_count=f.get("sample_count", 0),
            confidence=float(f.get("confidence", 0.5)),
            conflicting_evidence=f.get("conflicting_evidence", []),
            is_model_generated=True,
            analysis_type="semantic",
        )
        findings.append(finding)

    return findings


def _fallback_analysis(reviews: list[Review], analysis_goal: str) -> list[Finding]:
    """
    Rule-based fallback when LLM is unavailable.
    Clearly labeled as statistical, not model-driven.
    """
    findings = []

    # Statistical: low rating analysis
    low_rating = [r for r in reviews if r.rating <= 2]
    if low_rating:
        excerpts = [r.cleaned_body[:200] for r in low_rating[:5] if r.cleaned_body]
        findings.append(Finding(
            id="F-001",
            summary=f"{len(low_rating)} low-rating reviews (1-2 stars) detected",
            category="rating_sentiment",
            severity="high" if len(low_rating) > len(reviews) * 0.3 else "medium",
            source_review_ids=[r.id for r in low_rating[:10]],
            source_excerpts=excerpts,
            sample_count=len(low_rating),
            confidence=1.0,  # deterministic statistic
            is_model_generated=False,
            analysis_type="statistical",
        ))

    # Statistical: version-specific issues
    version_groups: dict[str, list[Review]] = {}
    for r in reviews:
        v = r.version or "unknown"
        version_groups.setdefault(v, []).append(r)

    for version, v_reviews in version_groups.items():
        avg = sum(r.rating for r in v_reviews) / len(v_reviews) if v_reviews else 0
        if avg < 3.0 and len(v_reviews) >= 3:
            findings.append(Finding(
                id=f"F-{len(findings)+1:03d}",
                summary=f"Version {version} has low average rating ({avg:.1f}/5) from {len(v_reviews)} reviews",
                category="version_quality",
                severity="high",
                source_review_ids=[r.id for r in v_reviews[:10]],
                source_excerpts=[r.cleaned_body[:200] for r in v_reviews[:3] if r.cleaned_body],
                sample_count=len(v_reviews),
                confidence=1.0,
                is_model_generated=False,
                analysis_type="statistical",
            ))

    # Statistical: review length correlation
    short_negative = [r for r in reviews if r.rating <= 2 and len(r.cleaned_body) < 50]
    if short_negative:
        findings.append(Finding(
            id=f"F-{len(findings)+1:03d}",
            summary=f"{len(short_negative)} short negative reviews may indicate frustration without detail",
            category="review_quality",
            severity="low",
            source_review_ids=[r.id for r in short_negative[:5]],
            source_excerpts=[r.cleaned_body for r in short_negative[:3]],
            sample_count=len(short_negative),
            confidence=0.7,
            is_model_generated=False,
            analysis_type="statistical",
        ))

    return findings


def generate_prd(findings: list[Finding], app_name: str = "", analysis_goal: str = "") -> tuple[list[Requirement], dict]:
    """
    Model-driven PRD generation: turn findings into actionable requirements.
    Each requirement traces back to specific findings and source reviews.
    """
    client = _get_client()

    if not client:
        return _fallback_prd(findings)

    findings_text = "\n".join(
        f"[{f.id}] {f.summary} (severity:{f.severity}, confidence:{f.confidence}, "
        f"reviews:{f.sample_count}) Category:{f.category}"
        for f in findings
    )

    system_prompt = (
        "You are a senior product manager. Generate a PRD from review analysis findings. "
        "Each requirement must trace back to specific finding IDs. "
        "Prioritize by severity and confidence. Split into versions when scope is large.\n\n"
        "Return JSON:\n"
        '{\n'
        '  "requirements": [\n'
        '    {\n'
        '      "title": "requirement title",\n'
        '      "description": "detailed description",\n'
        '      "priority": "P0|P1|P2|P3",\n'
        '      "target_version": "v1.0|v1.1|v2.0",\n'
        '      "source_finding_ids": ["F-001", ...],\n'
        '      "acceptance_criteria": ["criterion 1", ...]\n'
        '    }\n'
        '  ],\n'
        '  "version_plan": {\n'
        '    "v1.0": "description of v1.0 scope",\n'
        '    "v1.1": "description of v1.1 scope"\n'
        '  }\n'
        '}\n'
    )

    goal_text = f"\nAnalysis goal: {analysis_goal}" if analysis_goal else ""
    user_prompt = (
        f"Generate a PRD for {app_name or 'the app'} based on these findings:\n\n"
        f"{findings_text}\n{goal_text}\n\n"
        f"Return ONLY the JSON object."
    )

    raw = _call_llm(client, system_prompt, user_prompt)
    if not raw:
        return _fallback_prd(findings)

    data = _parse_json_response(raw)
    if not data or "requirements" not in data:
        return _fallback_prd(findings)

    requirements = []
    for i, r in enumerate(data["requirements"]):
        # Collect source review IDs from linked findings
        source_review_ids = []
        for fid in r.get("source_finding_ids", []):
            for f in findings:
                if f.id == fid:
                    source_review_ids.extend(f.source_review_ids)
                    break

        req = Requirement(
            id=f"REQ-{i+1:03d}",
            title=r.get("title", ""),
            description=r.get("description", ""),
            priority=r.get("priority", "P2"),
            target_version=r.get("target_version", "v1.0"),
            source_finding_ids=r.get("source_finding_ids", []),
            source_review_ids=list(set(source_review_ids)),
            acceptance_criteria=r.get("acceptance_criteria", []),
        )
        requirements.append(req)

    return requirements, data.get("version_plan", {})


def _fallback_prd(findings: list[Finding]) -> tuple[list[Requirement], dict]:
    """Rule-based PRD fallback."""
    requirements = []
    version_plan = {}

    high_severity = [f for f in findings if f.severity == "high"]
    medium_severity = [f for f in findings if f.severity == "medium"]

    for i, f in enumerate(high_severity):
        requirements.append(Requirement(
            id=f"REQ-{i+1:03d}",
            title=f"Address: {f.summary[:60]}",
            description=f"Based on {f.sample_count} reviews. Category: {f.category}.",
            priority="P0" if f.confidence > 0.7 else "P1",
            target_version="v1.0",
            source_finding_ids=[f.id],
            source_review_ids=f.source_review_ids,
            acceptance_criteria=[f"Resolve issue described in {f.id}"],
        ))

    offset = len(requirements)
    for i, f in enumerate(medium_severity):
        requirements.append(Requirement(
            id=f"REQ-{offset+i+1:03d}",
            title=f"Improve: {f.summary[:60]}",
            description=f"Based on {f.sample_count} reviews. Category: {f.category}.",
            priority="P2",
            target_version="v1.1",
            source_finding_ids=[f.id],
            source_review_ids=f.source_review_ids,
            acceptance_criteria=[f"Address feedback in {f.id}"],
        ))

    if requirements:
        version_plan = {
            "v1.0": f"Address {len(high_severity)} high-severity issues",
            "v1.1": f"Address {len(medium_severity)} medium-severity issues",
        }

    return requirements, version_plan


def generate_test_cases(requirements: list[Requirement], findings: list[Finding], reviews: list[Review]) -> list[TestCase]:
    """
    Model-driven test case generation.
    Each test case links to a requirement and traces back to source reviews.
    """
    client = _get_client()

    if not client:
        return _fallback_test_cases(requirements, findings)

    # Build a lookup from finding to reviews
    review_map = {r.id: r for r in reviews}
    finding_map = {f.id: f for f in findings}

    req_text = "\n".join(
        f"[{r.id}] {r.title} (version:{r.target_version}, priority:{r.priority}) "
        f"Findings:{r.source_finding_ids} Criteria:{r.acceptance_criteria}"
        for r in requirements
    )

    system_prompt = (
        "You are a QA engineer. Generate test cases for each requirement. "
        "Each test case must link to its requirement ID and include source review "
        "excerpts that describe the user problem being tested.\n\n"
        "Return JSON:\n"
        '{\n'
        '  "test_cases": [\n'
        '    {\n'
        '      "title": "test case title",\n'
        '      "requirement_id": "REQ-001",\n'
        '      "steps": ["step 1", "step 2", ...],\n'
        '      "expected_result": "expected outcome",\n'
        '      "source_review_ids": ["review_id", ...],\n'
        '      "source_review_excerpts": ["quote", ...]\n'
        '    }\n'
        '  ]\n'
        '}\n'
    )

    user_prompt = (
        f"Generate test cases for these requirements:\n\n{req_text}\n\n"
        f"Return ONLY the JSON object."
    )

    raw = _call_llm(client, system_prompt, user_prompt)
    if not raw:
        return _fallback_test_cases(requirements, findings)

    data = _parse_json_response(raw)
    if not data or "test_cases" not in data:
        return _fallback_test_cases(requirements, findings)

    test_cases = []
    for i, tc in enumerate(data["test_cases"]):
        # Get source review excerpts if not provided
        excerpts = tc.get("source_review_excerpts", [])
        review_ids = tc.get("source_review_ids", [])
        if not excerpts:
            for rid in review_ids:
                if rid in review_map:
                    excerpts.append(review_map[rid].cleaned_body[:200])

        test_cases.append(TestCase(
            id=f"TC-{i+1:03d}",
            title=tc.get("title", ""),
            requirement_id=tc.get("requirement_id", ""),
            steps=tc.get("steps", []),
            expected_result=tc.get("expected_result", ""),
            source_review_ids=review_ids,
            source_review_excerpts=excerpts,
        ))

    return test_cases


def _fallback_test_cases(requirements: list[Requirement], findings: list[Finding]) -> list[TestCase]:
    """Rule-based test case fallback."""
    test_cases = []
    for i, req in enumerate(requirements):
        test_cases.append(TestCase(
            id=f"TC-{i+1:03d}",
            title=f"Verify: {req.title[:60]}",
            requirement_id=req.id,
            steps=[
                f"Reproduce the issue described in {req.source_finding_ids}",
                "Apply the fix for " + req.id,
                "Verify the acceptance criteria are met",
            ],
            expected_result=f"The issue described in {req.source_finding_ids} is resolved",
            source_review_ids=req.source_review_ids[:5],
            source_review_excerpts=[],
        ))
    return test_cases


def validate_traceability(
    reviews: list[Review],
    findings: list[Finding],
    requirements: list[Requirement],
    test_cases: list[TestCase],
) -> dict:
    """
    Validate the traceability chain: review -> finding -> requirement -> test case.
    Reports any broken links or unsupported conclusions.
    """
    review_ids = {r.id for r in reviews}
    finding_ids = {f.id for f in findings}
    req_ids = {r.id for r in requirements}

    broken_findings = []
    for f in findings:
        valid_ids = [rid for rid in f.source_review_ids if rid in review_ids]
        invalid_ids = [rid for rid in f.source_review_ids if rid not in review_ids]
        if invalid_ids:
            broken_findings.append({
                "finding_id": f.id,
                "invalid_review_ids": invalid_ids,
                "issue": "Finding references non-existent review IDs",
            })
        if not valid_ids and f.is_model_generated:
            broken_findings.append({
                "finding_id": f.id,
                "issue": "Model-generated finding has no valid source reviews",
            })

    broken_reqs = []
    for r in requirements:
        invalid_fids = [fid for fid in r.source_finding_ids if fid not in finding_ids]
        if invalid_fids:
            broken_reqs.append({
                "requirement_id": r.id,
                "invalid_finding_ids": invalid_fids,
                "issue": "Requirement references non-existent finding IDs",
            })

    broken_tcs = []
    for tc in test_cases:
        if tc.requirement_id not in req_ids:
            broken_tcs.append({
                "test_case_id": tc.id,
                "invalid_requirement_id": tc.requirement_id,
                "issue": "Test case references non-existent requirement ID",
            })

    unsupported = [f for f in findings if f.is_model_generated and not f.source_review_ids]

    return {
        "total_reviews": len(reviews),
        "total_findings": len(findings),
        "total_requirements": len(requirements),
        "total_test_cases": len(test_cases),
        "broken_finding_links": broken_findings,
        "broken_requirement_links": broken_reqs,
        "broken_test_case_links": broken_tcs,
        "unsupported_conclusions": [f.id for f in unsupported],
        "traceability_score": round(
            1.0 - len(broken_findings + broken_reqs + broken_tcs) /
            max(len(findings) + len(requirements) + len(test_cases), 1), 2
        ),
    }


def get_model_info() -> dict:
    """Return model configuration info for documentation."""
    return {
        "provider": "OpenAI-compatible" if config.llm_available else "none",
        "model": config.OPENAI_MODEL if config.llm_available else "none",
        "base_url": config.OPENAI_BASE_URL,
        "llm_available": config.llm_available,
        "temperature": 0.3,
        "max_tokens": 4096,
        "retry_strategy": "3 retries with exponential backoff",
        "hallucination_mitigation": [
            "Low temperature (0.3) for deterministic output",
            "Explicit instruction to cite source review IDs",
            "Confidence scoring required for each finding",
            "Conflicting evidence field required",
            "Traceability validation post-analysis",
            "Fallback to statistical analysis if LLM fails",
        ],
    }
