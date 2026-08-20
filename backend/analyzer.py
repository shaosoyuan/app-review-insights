"""
LLM-powered analyzer - the core semantic analysis engine.

This module uses an LLM (via OpenAI-compatible API) to perform:
1. Dynamic topic discovery and review classification (not keyword-based)
2. Issue consolidation with evidence grounding
3. PRD generation from findings
4. Test case generation from requirements

All model-generated conclusions include source review IDs, confidence, and uncertainty markers.
"""
import os
import json
import httpx
from models import Finding, Requirement, TestCase, PRDDraft, CleanedReview
from typing import Optional


def get_llm_config() -> dict:
    """Load LLM configuration from environment."""
    return {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }


def is_llm_configured() -> bool:
    """Check if LLM is properly configured."""
    config = get_llm_config()
    return bool(config["api_key"] and config["api_key"] != "sk-your-api-key-here")


async def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
    """Call the LLM via OpenAI-compatible API."""
    config = get_llm_config()
    
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    
    url = f"{config['base_url'].rstrip('/')}/chat/completions"
    
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _prepare_reviews_for_llm(reviews: list[CleanedReview], max_reviews: int = 100) -> str:
    """Format reviews into a compact text for LLM input."""
    lines = []
    for i, r in enumerate(reviews[:max_reviews]):
        lines.append(
            f"[ID:{r.review_id}] Rating:{r.rating}/5 Version:{r.version or 'N/A'} "
            f"| Title: {r.title} | Content: {r.content[:300]}"
        )
    return "\n".join(lines)


async def analyze_reviews(reviews: list[CleanedReview], analysis_goal: str = "") -> list[Finding]:
    """
    Use LLM to dynamically classify and analyze reviews.
    
    This is the core model-driven semantic task:
    - Discovers topics dynamically (no predefined taxonomy)
    - Consolidates issues with evidence
    - Identifies conflicts and uncertainty
    """
    if not reviews:
        return []
    
    if not is_llm_configured():
        return _fallback_analysis(reviews)
    
    reviews_text = _prepare_reviews_for_llm(reviews, max_reviews=80)
    
    system_prompt = """You are a senior product analyst. Your task is to analyze App Store reviews and identify actionable product findings.

CRITICAL RULES:
1. Each finding MUST include the specific review IDs that support it.
2. Each finding MUST include direct excerpts from those reviews.
3. Each finding MUST include a confidence score (0.0-1.0) reflecting how strong the evidence is.
4. If there is conflicting evidence (e.g., some users love a feature while others hate it), note it explicitly.
5. If sample size is small or evidence is weak, state the uncertainty.
6. Do NOT fabricate review IDs or excerpts. Only use IDs and text from the provided data.
7. Categories should be discovered dynamically from the data, not from a predefined list.

Return a JSON array of findings. Each finding object must have:
- "category": string (discovered from data)
- "summary": string (concise problem/insight description)
- "severity": "critical" | "high" | "medium" | "low"
- "source_review_ids": array of strings (exact review IDs)
- "source_excerpts": array of strings (direct quotes from reviews)
- "sample_count": integer (number of supporting reviews)
- "confidence": float (0.0-1.0)
- "uncertainty": string (describe any uncertainty)
- "conflicting_evidence": string or null (describe conflicts if any)

Return ONLY the JSON array, no other text."""

    goal_instruction = ""
    if analysis_goal:
        goal_instruction = f"\n\nThe analysis goal/constraint is: {analysis_goal}\nFocus the analysis accordingly."
    
    user_prompt = f"Analyze the following {len(reviews)} App Store reviews.{goal_instruction}\n\nReviews:\n{reviews_text}"
    
    try:
        response = await call_llm(system_prompt, user_prompt, max_tokens=4096)
        
        # Parse JSON from response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()
        
        findings_data = json.loads(response)
        
        findings = []
        for i, f in enumerate(findings_data):
            finding = Finding(
                finding_id=f"F{i+1:03d}",
                category=f.get("category", "Uncategorized"),
                summary=f.get("summary", ""),
                severity=f.get("severity", "medium"),
                source_review_ids=f.get("source_review_ids", []),
                source_excerpts=f.get("source_excerpts", []),
                sample_count=f.get("sample_count", 0),
                confidence=f.get("confidence", 0.5),
                uncertainty=f.get("uncertainty", ""),
                conflicting_evidence=f.get("conflicting_evidence"),
                is_model_generated=True,
            )
            findings.append(finding)
        
        return findings
    except Exception as e:
        return _fallback_analysis(reviews, str(e))


async def generate_prd(findings: list[Finding], app_name: str, analysis_goal: str = "") -> PRDDraft:
    """Use LLM to generate a PRD from findings."""
    if not findings:
        return PRDDraft(
            title=f"{app_name} - Product Requirements Document",
            overview="No findings to generate PRD from.",
            target_audience="App Store users",
        )
    
    findings_text = "\n".join([
        f"- [{f.finding_id}] ({f.severity}) {f.category}: {f.summary} "
        f"(Confidence: {f.confidence}, Samples: {f.sample_count})"
        for f in findings
    ])
    
    if not is_llm_configured():
        return _fallback_prd(findings, app_name)
    
    system_prompt = """You are a senior product manager. Generate a PRD from the provided findings.

CRITICAL RULES:
1. Each requirement MUST trace back to specific finding IDs.
2. Requirements should be actionable and specific.
3. Assign priority: P0 (must-have, critical issues), P1 (should-have, high impact), P2 (nice-to-have).
4. Split into versions: v1.0 (P0 items), v2.0 (P1 items), v3.0 (P2 items).
5. Include open questions where evidence is insufficient.

Return a JSON object with:
- "title": string
- "overview": string (2-3 paragraphs)
- "target_audience": string
- "requirements": array of {req_id, title, description, priority, source_finding_ids, source_review_ids, version}
- "version_plan": array of {version, description, requirements}
- "open_questions": array of strings

Return ONLY the JSON object, no other text."""

    user_prompt = f"""App: {app_name}
Analysis Goal: {analysis_goal or 'General analysis'}

Findings:
{findings_text}

Generate a comprehensive PRD."""

    try:
        response = await call_llm(system_prompt, user_prompt, max_tokens=4096)
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()
        
        prd_data = json.loads(response)
        
        requirements = []
        for r in prd_data.get("requirements", []):
            requirements.append(Requirement(
                req_id=r.get("req_id", ""),
                title=r.get("title", ""),
                description=r.get("description", ""),
                priority=r.get("priority", "P2"),
                source_finding_ids=r.get("source_finding_ids", []),
                source_review_ids=r.get("source_review_ids", []),
                version=r.get("version", "v1.0"),
            ))
        
        return PRDDraft(
            title=prd_data.get("title", f"{app_name} - PRD"),
            overview=prd_data.get("overview", ""),
            target_audience=prd_data.get("target_audience", ""),
            requirements=requirements,
            version_plan=prd_data.get("version_plan", []),
            open_questions=prd_data.get("open_questions", []),
        )
    except Exception:
        return _fallback_prd(findings, app_name)


async def generate_test_cases(prd: PRDDraft, findings: list[Finding]) -> list[TestCase]:
    """Use LLM to generate test cases from PRD requirements."""
    if not prd.requirements:
        return []
    
    if not is_llm_configured():
        return _fallback_test_cases(prd)
    
    reqs_text = "\n".join([
        f"- [{r.req_id}] ({r.priority}) {r.title}: {r.description} "
        f"(Source findings: {r.source_finding_ids})"
        for r in prd.requirements
    ])
    
    findings_map = {f.finding_id: f for f in findings}
    findings_text = "\n".join([
        f"- [{f.finding_id}] {f.summary} (Reviews: {f.source_review_ids})"
        for f in findings
    ])
    
    system_prompt = """You are a senior QA engineer. Generate test cases for the given requirements.

CRITICAL RULES:
1. Each test case MUST link to a specific requirement ID.
2. Each test case should reference the source review IDs that motivated the requirement.
3. Test cases should verify whether the requirement solves the user's problem.
4. Include clear steps and expected results.

Return a JSON array of test cases. Each test case object must have:
- "title": string
- "description": string
- "steps": array of strings
- "expected_result": string
- "requirement_id": string (must match a requirement ID)
- "source_review_ids": array of strings (from the findings)

Return ONLY the JSON array, no other text."""

    user_prompt = f"""Requirements:
{reqs_text}

Findings with source reviews:
{findings_text}

Generate test cases for each requirement."""

    try:
        response = await call_llm(system_prompt, user_prompt, max_tokens=4096)
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()
        
        tc_data = json.loads(response)
        
        test_cases = []
        for i, tc in enumerate(tc_data):
            test_cases.append(TestCase(
                test_id=f"TC{i+1:03d}",
                title=tc.get("title", ""),
                description=tc.get("description", ""),
                steps=tc.get("steps", []),
                expected_result=tc.get("expected_result", ""),
                requirement_id=tc.get("requirement_id", ""),
                source_review_ids=tc.get("source_review_ids", []),
            ))
        
        return test_cases
    except Exception:
        return _fallback_test_cases(prd)


def build_traceability_matrix(
    reviews: list, findings: list[Finding], 
    prd: Optional[PRDDraft], test_cases: list[TestCase]
) -> list[dict]:
    """Build traceability chain: Review -> Finding -> Requirement -> Test Case."""
    matrix = []
    
    req_by_finding = {}
    if prd:
        for req in prd.requirements:
            for fid in req.source_finding_ids:
                req_by_finding.setdefault(fid, []).append(req)
    
    tc_by_req = {}
    for tc in test_cases:
        tc_by_req.setdefault(tc.requirement_id, []).append(tc)
    
    for finding in findings:
        reqs = req_by_finding.get(finding.finding_id, [])
        for req in reqs:
            tcs = tc_by_req.get(req.req_id, [])
            for tc in tcs:
                matrix.append({
                    "review_ids": finding.source_review_ids,
                    "finding_id": finding.finding_id,
                    "finding_summary": finding.summary,
                    "requirement_id": req.req_id,
                    "requirement_title": req.title,
                    "test_case_id": tc.test_id,
                    "test_case_title": tc.title,
                    "traceability_valid": True,
                })
            if not tcs:
                matrix.append({
                    "review_ids": finding.source_review_ids,
                    "finding_id": finding.finding_id,
                    "finding_summary": finding.summary,
                    "requirement_id": req.req_id,
                    "requirement_title": req.title,
                    "test_case_id": None,
                    "test_case_title": None,
                    "traceability_valid": False,
                    "note": "No test case generated for this requirement",
                })
        if not reqs:
            matrix.append({
                "review_ids": finding.source_review_ids,
                "finding_id": finding.finding_id,
                "finding_summary": finding.summary,
                "requirement_id": None,
                "requirement_title": None,
                "test_case_id": None,
                "test_case_title": None,
                "traceability_valid": False,
                "note": "No requirement generated for this finding",
            })
    
    return matrix


# ---- Fallback methods (when LLM is not configured) ----

def _fallback_analysis(reviews: list[CleanedReview], error: str = "") -> list[Finding]:
    """Rule-based fallback analysis when LLM is unavailable."""
    findings = []
    
    # Rating distribution
    low_rating = [r for r in reviews if r.rating <= 2 and not r.is_duplicate]
    if low_rating:
        findings.append(Finding(
            finding_id="F001",
            category="Low Rating Issues",
            summary=f"{len(low_rating)} reviews gave 1-2 stars, indicating significant user dissatisfaction.",
            severity="high",
            source_review_ids=[r.review_id for r in low_rating[:10]],
            source_excerpts=[r.content[:200] for r in low_rating[:5]],
            sample_count=len(low_rating),
            confidence=0.9,
            uncertainty=f"Rule-based analysis (LLM unavailable{f': {error}' if error else ''}). Categories not dynamically discovered.",
            conflicting_evidence=None,
            is_model_generated=False,
        ))
    
    high_rating = [r for r in reviews if r.rating >= 4 and not r.is_duplicate]
    if high_rating:
        findings.append(Finding(
            finding_id="F002",
            category="Positive Feedback",
            summary=f"{len(high_rating)} reviews gave 4-5 stars, indicating user satisfaction with core features.",
            severity="low",
            source_review_ids=[r.review_id for r in high_rating[:10]],
            source_excerpts=[r.content[:200] for r in high_rating[:5]],
            sample_count=len(high_rating),
            confidence=0.9,
            uncertainty="Rule-based analysis. Categories not dynamically discovered.",
            conflicting_evidence=None,
            is_model_generated=False,
        ))
    
    # Duplicate content
    duplicates = [r for r in reviews if r.is_duplicate]
    if duplicates:
        findings.append(Finding(
            finding_id="F003",
            category="Data Quality",
            summary=f"{len(duplicates)} duplicate or near-duplicate reviews detected.",
            severity="low",
            source_review_ids=[r.review_id for r in duplicates[:5]],
            source_excerpts=[],
            sample_count=len(duplicates),
            confidence=1.0,
            uncertainty="Deterministic detection via text similarity.",
            is_model_generated=False,
        ))
    
    if not findings:
        findings.append(Finding(
            finding_id="F001",
            category="Insufficient Data",
            summary="Not enough review data to perform meaningful analysis.",
            severity="medium",
            source_review_ids=[],
            source_excerpts=[],
            sample_count=0,
            confidence=0.3,
            uncertainty="No reviews available for analysis.",
            is_model_generated=False,
        ))
    
    return findings


def _fallback_prd(findings: list[Finding], app_name: str) -> PRDDraft:
    """Rule-based fallback PRD."""
    requirements = []
    for i, f in enumerate(findings):
        if f.severity in ("critical", "high"):
            requirements.append(Requirement(
                req_id=f"REQ-{i+1:03d}",
                title=f"Address: {f.category}",
                description=f"Based on finding {f.finding_id}: {f.summary}",
                priority="P0" if f.severity == "critical" else "P1",
                source_finding_ids=[f.finding_id],
                source_review_ids=f.source_review_ids,
                version="v1.0",
            ))
        else:
            requirements.append(Requirement(
                req_id=f"REQ-{i+1:03d}",
                title=f"Monitor: {f.category}",
                description=f"Based on finding {f.finding_id}: {f.summary}",
                priority="P2",
                source_finding_ids=[f.finding_id],
                source_review_ids=f.source_review_ids,
                version="v2.0",
            ))
    
    return PRDDraft(
        title=f"{app_name} - Product Requirements Document",
        overview=f"This PRD was generated from {len(findings)} findings derived from App Store reviews. "
                 f"Note: LLM was not configured, so this is a rule-based fallback PRD.",
        target_audience="App Store users",
        requirements=requirements,
        version_plan=[
            {"version": "v1.0", "description": "Critical and high-priority fixes", "requirements": [r.req_id for r in requirements if r.version == "v1.0"]},
            {"version": "v2.0", "description": "Medium-priority improvements", "requirements": [r.req_id for r in requirements if r.version == "v2.0"]},
        ],
        open_questions=["Configure LLM API for model-driven PRD generation"],
    )


def _fallback_test_cases(prd: PRDDraft) -> list[TestCase]:
    """Rule-based fallback test cases."""
    test_cases = []
    for i, req in enumerate(prd.requirements):
        test_cases.append(TestCase(
            test_id=f"TC{i+1:03d}",
            title=f"Verify: {req.title}",
            description=f"Test that requirement {req.req_id} is properly implemented.",
            steps=[
                f"1. Set up test environment for {req.title}",
                f"2. Reproduce the scenario described in source reviews",
                f"3. Verify the fix addresses the user issue",
            ],
            expected_result="The user issue described in source reviews is resolved.",
            requirement_id=req.req_id,
            source_review_ids=req.source_review_ids,
        ))
    return test_cases
