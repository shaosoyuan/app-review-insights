"""
FastAPI main application - App Review Insights API.

Endpoints:
- GET  /                    -> API info
- GET  /api/health          -> Health check
- POST /api/collect         -> Collect reviews from App Store or uploaded file
- POST /api/analyze         -> Run LLM analysis on collected reviews
- GET  /api/analyze/stream  -> SSE stream for analysis progress
- GET  /api/results/{job_id}-> Get analysis results
- GET  /api/sample          -> Get sample data for demo without API key
"""
import json
import uuid
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from datetime import datetime

from .models import Review, Finding, Requirement, TestCase, AnalysisResult
from .config import config
from .collector import fetch_reviews, fetch_app_info, extract_app_id, fetch_reviews_from_file
from .cleaner import clean_reviews, get_rating_distribution, get_version_distribution
from .analyzer import (
    analyze_reviews, generate_prd, generate_test_cases,
    validate_traceability, get_model_info,
)

app = FastAPI(
    title="App Review Insights API",
    description="LLM-powered App Store review analysis pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend static files directory
frontend_dir = Path(__file__).parent.parent / "frontend"

# In-memory job storage
jobs: dict[str, AnalysisResult] = {}


# --- Request Models ---

class CollectRequest(BaseModel):
    app_url_or_id: str
    max_reviews: int = 200


class AnalyzeRequest(BaseModel):
    reviews: Optional[list[dict]] = None
    analysis_goal: str = ""


# --- Routes ---

@app.get("/")
async def root():
    return {
        "name": "App Review Insights API",
        "version": "1.0.0",
        "llm_available": config.llm_available,
        "model": config.OPENAI_MODEL if config.llm_available else None,
        "endpoints": [
            "/api/health",
            "/api/collect",
            "/api/analyze",
            "/api/analyze/stream",
            "/api/results/{job_id}",
            "/api/sample",
        ],
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "llm_available": config.llm_available,
        "model_info": get_model_info(),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/collect")
async def collect_reviews(req: CollectRequest):
    """Collect reviews from App Store via iTunes RSS API."""
    app_id = extract_app_id(req.app_url_or_id)
    if not app_id:
        raise HTTPException(status_code=400, detail="Invalid App Store URL or ID")

    app_info = fetch_app_info(app_id)
    reviews = fetch_reviews(app_id, max_reviews=req.max_reviews)

    if not reviews:
        raise HTTPException(status_code=404, detail="No reviews found for this app")

    cleaned, duplicates = clean_reviews(reviews)
    rating_dist = get_rating_distribution(cleaned)
    version_dist = get_version_distribution(cleaned)

    return {
        "app_info": app_info,
        "total_collected": len(reviews),
        "duplicates_removed": duplicates,
        "total_cleaned": len(cleaned),
        "rating_distribution": rating_dist,
        "version_distribution": version_dist,
        "reviews": [r.model_dump() for r in cleaned],
    }


@app.post("/api/collect/upload")
async def collect_from_upload(file: UploadFile = File(...)):
    """Collect reviews from uploaded JSON or CSV file."""
    content = await file.read()
    reviews = fetch_reviews_from_file(content, file.filename)
    if not reviews:
        raise HTTPException(status_code=400, detail="No valid reviews found in file")

    cleaned, duplicates = clean_reviews(reviews)
    rating_dist = get_rating_distribution(cleaned)
    version_dist = get_version_distribution(cleaned)

    return {
        "filename": file.filename,
        "total_collected": len(reviews),
        "duplicates_removed": duplicates,
        "total_cleaned": len(cleaned),
        "rating_distribution": rating_dist,
        "version_distribution": version_dist,
        "reviews": [r.model_dump() for r in cleaned],
    }


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Run full analysis pipeline (non-streaming)."""
    if not req.reviews:
        raise HTTPException(status_code=400, detail="No reviews provided")

    reviews = [Review(**r) for r in req.reviews]
    job_id = str(uuid.uuid4())[:8]

    result = _run_pipeline(reviews, req.analysis_goal)
    jobs[job_id] = result

    return {"job_id": job_id, "result": result.model_dump()}


@app.get("/api/analyze/stream")
async def analyze_stream(app_url_or_id: str, analysis_goal: str = "", max_reviews: int = 200):
    """
    SSE streaming endpoint for real-time analysis progress.
    Collects reviews, runs analysis pipeline, and streams progress events.
    """
    async def event_generator():
        job_id = str(uuid.uuid4())[:8]

        def send_event(event: str, data: dict):
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        # Step 1: Collect
        yield send_event("progress", {"step": 1, "total_steps": 5, "message": "Collecting reviews from App Store..."})

        app_id = extract_app_id(app_url_or_id)
        if not app_id:
            yield send_event("error", {"message": "Invalid App Store URL or ID"})
            return

        app_info = fetch_app_info(app_id)
        reviews = fetch_reviews(app_id, max_reviews=max_reviews)

        if not reviews:
            yield send_event("error", {"message": "No reviews found"})
            return

        yield send_event("progress", {
            "step": 1, "total_steps": 5, "message": f"Collected {len(reviews)} reviews",
            "app_info": app_info,
        })

        # Step 2: Clean
        yield send_event("progress", {"step": 2, "total_steps": 5, "message": "Cleaning and deduplicating..."})
        cleaned, duplicates = clean_reviews(reviews)
        rating_dist = get_rating_distribution(cleaned)
        version_dist = get_version_distribution(cleaned)
        yield send_event("progress", {
            "step": 2, "total_steps": 5, "message": f"Cleaned: {len(cleaned)} reviews ({duplicates} duplicates removed)",
            "rating_distribution": rating_dist,
            "version_distribution": version_dist,
        })

        # Step 3: Analyze (LLM)
        yield send_event("progress", {"step": 3, "total_steps": 5, "message": "Running LLM semantic analysis..."})
        findings = analyze_reviews(cleaned, analysis_goal)
        yield send_event("progress", {
            "step": 3, "total_steps": 5, "message": f"Discovered {len(findings)} findings",
            "findings": [f.model_dump() for f in findings],
        })

        # Step 4: PRD
        yield send_event("progress", {"step": 4, "total_steps": 5, "message": "Generating PRD..."})
        requirements, version_plan = generate_prd(findings, app_info.get("trackName", ""), analysis_goal)
        yield send_event("progress", {
            "step": 4, "total_steps": 5, "message": f"Generated {len(requirements)} requirements",
            "requirements": [r.model_dump() for r in requirements],
            "version_plan": version_plan,
        })

        # Step 5: Test cases
        yield send_event("progress", {"step": 5, "total_steps": 5, "message": "Generating test cases..."})
        test_cases = generate_test_cases(requirements, findings, cleaned)
        yield send_event("progress", {
            "step": 5, "total_steps": 5, "message": f"Generated {len(test_cases)} test cases",
            "test_cases": [tc.model_dump() for tc in test_cases],
        })

        # Final result
        traceability = validate_traceability(cleaned, findings, requirements, test_cases)
        result = AnalysisResult(
            job_id=job_id,
            app_info=app_info,
            total_reviews=len(cleaned),
            duplicates_removed=duplicates,
            rating_distribution=rating_dist,
            version_distribution=version_dist,
            findings=findings,
            requirements=requirements,
            test_cases=test_cases,
            version_plan=version_plan,
            traceability_report=traceability,
            model_info=get_model_info(),
        )
        jobs[job_id] = result

        yield send_event("complete", {"job_id": job_id, "result": result.model_dump()})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/results/{job_id}")
async def get_results(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id].model_dump()


@app.get("/api/sample")
async def get_sample_data():
    """Return sample data for demo without API key or real app."""
    sample_reviews = [
        Review(id="s1", rating=1, title="Crashes on startup", body="App crashes immediately after opening. Tried reinstalling but same issue. iPhone 14 Pro, iOS 17.2.", author="user1", version="3.2.1"),
        Review(id="s2", rating=2, title="Keeps crashing", body="Was working fine until the latest update. Now it crashes every time I try to open my projects.", author="user2", version="3.2.1"),
        Review(id="s3", rating=1, title="Broken after update", body="The new update broke everything. Can't open any of my saved work. Very frustrated.", author="user3", version="3.2.1"),
        Review(id="s4", rating=3, title="Good app but buggy", body="I love the concept but there are too many bugs. Export feature doesn't work half the time.", author="user4", version="3.1.0"),
        Review(id="s5", rating=5, title="Best app ever", body="This app changed my workflow completely. The AI features are amazing and save me hours every week.", author="user5", version="3.1.0"),
        Review(id="s6", rating=4, title="Great but needs dark mode", body="Really useful app. Would be perfect with dark mode support for night usage.", author="user6", version="3.1.0"),
        Review(id="s7", rating=2, title="Export broken", body="PDF export produces blank pages. This is a critical feature for my work. Please fix.", author="user7", version="3.2.1"),
        Review(id="s8", rating=3, title="Slow performance", body="App becomes very slow when working with large files. Needs performance optimization.", author="user8", version="3.2.0"),
        Review(id="s9", rating=5, title="Excellent tool", body="The collaboration features are top-notch. My team uses it every day.", author="user9", version="3.0.0"),
        Review(id="s10", rating=1, title="Lost my data", body="After the update all my projects disappeared. This is unacceptable. I need my data back.", author="user10", version="3.2.1"),
        Review(id="s11", rating=4, title="Love it", body="Great app for productivity. The UI is clean and intuitive.", author="user11", version="3.0.0"),
        Review(id="s12", rating=2, title="Too expensive now", body="The new pricing is ridiculous. $20/month for features that used to be free.", author="user12", version="3.2.0"),
    ]

    cleaned, duplicates = clean_reviews(sample_reviews)
    rating_dist = get_rating_distribution(cleaned)
    version_dist = get_version_distribution(cleaned)

    findings = analyze_reviews(cleaned)
    requirements, version_plan = generate_prd(findings, "Sample App")
    test_cases = generate_test_cases(requirements, findings, cleaned)
    traceability = validate_traceability(cleaned, findings, requirements, test_cases)

    result = AnalysisResult(
        job_id="sample",
        app_info={"trackName": "Sample App", "bundleId": "com.example.sample"},
        total_reviews=len(cleaned),
        duplicates_removed=duplicates,
        rating_distribution=rating_dist,
        version_distribution=version_dist,
        findings=findings,
        requirements=requirements,
        test_cases=test_cases,
        version_plan=version_plan,
        traceability_report=traceability,
        model_info=get_model_info(),
    )
    jobs["sample"] = result

    return result.model_dump()


# --- Static file serving for frontend ---

@app.get("/app")
async def serve_frontend():
    """Serve the frontend HTML application."""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    raise HTTPException(status_code=404, detail="Frontend not found")


# --- Pipeline runner ---

def _run_pipeline(reviews: list[Review], analysis_goal: str) -> AnalysisResult:
    """Run full analysis pipeline synchronously."""
    cleaned, duplicates = clean_reviews(reviews)
    rating_dist = get_rating_distribution(cleaned)
    version_dist = get_version_distribution(cleaned)

    findings = analyze_reviews(cleaned, analysis_goal)
    requirements, version_plan = generate_prd(findings, "", analysis_goal)
    test_cases = generate_test_cases(requirements, findings, cleaned)
    traceability = validate_traceability(cleaned, findings, requirements, test_cases)

    return AnalysisResult(
        job_id=str(uuid.uuid4())[:8],
        total_reviews=len(cleaned),
        duplicates_removed=duplicates,
        rating_distribution=rating_dist,
        version_distribution=version_dist,
        findings=findings,
        requirements=requirements,
        test_cases=test_cases,
        version_plan=version_plan,
        traceability_report=traceability,
        model_info=get_model_info(),
    )
