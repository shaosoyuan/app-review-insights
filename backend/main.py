"""
FastAPI backend - serves the API and static frontend.
"""
import os
import sys
import json
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Add backend dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Review, AnalysisResult
from collector import extract_app_id, fetch_app_info, fetch_reviews, load_reviews_from_json, load_reviews_from_csv
from cleaner import clean_reviews, filter_by_goal
from analyzer import (
    analyze_reviews, generate_prd, generate_test_cases, 
    build_traceability_matrix, is_llm_configured, get_llm_config
)

app = FastAPI(title="App Review Insights")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load .env
from dotenv import load_dotenv
load_dotenv()

# Static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class AnalysisRequest(BaseModel):
    app_url: str
    analysis_goal: str = ""
    uploaded_reviews: Optional[list[dict]] = None


@app.get("/api/health")
async def health():
    return {"status": "ok", "llm_configured": is_llm_configured()}


@app.get("/api/model-info")
async def model_info():
    config = get_llm_config()
    return {
        "configured": is_llm_configured(),
        "model": config["model"] if is_llm_configured() else None,
        "base_url": config["base_url"] if is_llm_configured() else None,
    }


@app.post("/api/upload-reviews")
async def upload_reviews(file: UploadFile = File(...)):
    """Upload a JSON or CSV file with review data."""
    content = await file.read()
    filename = file.filename or "upload.json"
    suffix = Path(filename).suffix.lower()
    tmp_path = Path(tempfile.gettempdir()) / f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}{suffix}"
    tmp_path.write_bytes(content)
    
    try:
        if suffix == ".json":
            reviews = load_reviews_from_json(str(tmp_path))
        elif suffix == ".csv":
            reviews = load_reviews_from_csv(str(tmp_path))
        else:
            raise HTTPException(400, "Unsupported file format. Use .json or .csv")
        
        return {"reviews": [r.model_dump() for r in reviews], "count": len(reviews)}
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/analyze")
async def analyze(request: AnalysisRequest):
    """
    Run the full analysis pipeline with SSE streaming.
    Streams progress updates and final results.
    """
    async def event_stream():
        async def send_event(event: str, data: dict):
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            # Check if we have uploaded review data
            uploaded = request.uploaded_reviews or []
            has_upload = len(uploaded) > 0
            app_id = None
            app_name = "Uploaded Data"
            reviews = []

            if has_upload:
                # Step 1: Parse uploaded reviews
                yield await send_event("progress", {
                    "stage": "init", "status": "done",
                    "message": f"Loaded {len(uploaded)} reviews from upload"
                })

                # Try to extract app_id from URL if provided
                app_id = extract_app_id(request.app_url) if request.app_url and request.app_url != "uploaded-data" else None

                # Fetch app info if we have a valid app_id
                if app_id:
                    yield await send_event("progress", {
                        "stage": "app_info", "status": "running",
                        "message": f"Fetching app info for ID: {app_id}..."
                    })
                    try:
                        app_info = await fetch_app_info(app_id)
                        app_name = app_info.get("trackName", f"App {app_id}")
                    except Exception:
                        app_name = f"App {app_id}"
                else:
                    yield await send_event("progress", {
                        "stage": "app_info", "status": "done",
                        "message": "Using uploaded data (no App Store URL)"
                    })

                yield await send_event("progress", {
                    "stage": "app_info", "status": "done",
                    "message": f"App: {app_name}",
                    "data": {"app_name": app_name, "app_id": app_id or "uploaded"}
                })

                # Convert uploaded dicts to Review objects
                for item in uploaded:
                    reviews.append(Review(
                        review_id=str(item.get("review_id", item.get("id", ""))),
                        author=item.get("author", ""),
                        rating=int(item.get("rating", 0)),
                        title=item.get("title", ""),
                        content=item.get("content", item.get("body", "")),
                        version=item.get("version", ""),
                        date=item.get("date", ""),
                    ))

                yield await send_event("progress", {
                    "stage": "collect", "status": "done",
                    "message": f"Loaded {len(reviews)} reviews from uploaded data",
                    "data": {"count": len(reviews)}
                })
            else:
                # Step 1: Validate and extract app ID from URL
                yield await send_event("progress", {
                    "stage": "init", "status": "running",
                    "message": "Parsing App Store URL..."
                })

                app_id = extract_app_id(request.app_url)
                if not app_id:
                    yield await send_event("error", {"message": "Invalid App Store URL. Could not extract app ID."})
                    return

                # Step 2: Fetch app info
                yield await send_event("progress", {
                    "stage": "app_info", "status": "running",
                    "message": f"Fetching app info for ID: {app_id}..."
                })

                app_info = await fetch_app_info(app_id)
                app_name = app_info.get("trackName", f"App {app_id}")

                yield await send_event("progress", {
                    "stage": "app_info", "status": "done",
                    "message": f"App: {app_name}",
                    "data": {"app_name": app_name, "app_id": app_id}
                })

                # Step 3: Collect reviews
                yield await send_event("progress", {
                    "stage": "collect", "status": "running",
                    "message": "Collecting reviews from iTunes RSS Feed..."
                })

                reviews = await fetch_reviews(app_id, country="us", max_pages=10)

                yield await send_event("progress", {
                    "stage": "collect", "status": "done",
                    "message": f"Collected {len(reviews)} reviews",
                    "data": {"count": len(reviews)}
                })

                if not reviews:
                    yield await send_event("warning", {
                        "message": "No reviews found. The app may have no reviews in the US App Store, or the RSS feed is unavailable."
                    })
                    # Try cached data
                    cache_path = Path(__file__).parent.parent / "data" / "cache" / f"reviews_{app_id}.json"
                    if cache_path.exists():
                        reviews = load_reviews_from_json(str(cache_path))
                        yield await send_event("info", {"message": f"Loaded {len(reviews)} reviews from cache."})

                if not reviews:
                    yield await send_event("error", {"message": "No reviews available for analysis."})
                    return

            # Step 4: Clean reviews
            yield await send_event("progress", {
                "stage": "clean", "status": "running",
                "message": "Cleaning and deduplicating reviews..."
            })

            cleaned = clean_reviews(reviews)
            unique_reviews = [r for r in cleaned if not r.is_duplicate]
            duplicates = [r for r in cleaned if r.is_duplicate]

            yield await send_event("progress", {
                "stage": "clean", "status": "done",
                "message": f"Cleaned: {len(unique_reviews)} unique, {len(duplicates)} duplicates removed",
                "data": {
                    "total": len(cleaned),
                    "unique": len(unique_reviews),
                    "duplicates": len(duplicates),
                    "cleaned_reviews": [r.model_dump() for r in cleaned[:20]]
                }
            })

            # Step 5: Filter by goal
            filtered = filter_by_goal(unique_reviews, request.analysis_goal)

            yield await send_event("progress", {
                "stage": "filter", "status": "done",
                "message": f"Filtered to {len(filtered)} reviews based on goal: '{request.analysis_goal or 'all'}'"
            })

            # Step 6: LLM Analysis
            yield await send_event("progress", {
                "stage": "analyze", "status": "running",
                "message": f"Running {'LLM-driven' if is_llm_configured() else 'rule-based fallback'} semantic analysis..."
            })

            findings = await analyze_reviews(filtered, request.analysis_goal)

            yield await send_event("progress", {
                "stage": "analyze", "status": "done",
                "message": f"Discovered {len(findings)} findings",
                "data": {"findings": [f.model_dump() for f in findings]}
            })

            # Step 7: Generate PRD
            yield await send_event("progress", {
                "stage": "prd", "status": "running",
                "message": "Generating PRD from findings..."
            })

            prd = await generate_prd(findings, app_name, request.analysis_goal)

            yield await send_event("progress", {
                "stage": "prd", "status": "done",
                "message": f"PRD generated with {len(prd.requirements)} requirements",
                "data": {"prd": prd.model_dump()}
            })

            # Step 8: Generate test cases
            yield await send_event("progress", {
                "stage": "testcases", "status": "running",
                "message": "Generating test cases..."
            })

            test_cases = await generate_test_cases(prd, findings)

            yield await send_event("progress", {
                "stage": "testcases", "status": "done",
                "message": f"Generated {len(test_cases)} test cases",
                "data": {"test_cases": [tc.model_dump() for tc in test_cases]}
            })

            # Step 9: Traceability
            yield await send_event("progress", {
                "stage": "traceability", "status": "running",
                "message": "Building traceability matrix..."
            })

            matrix = build_traceability_matrix(filtered, findings, prd, test_cases)
            unvalidated = [m for m in matrix if not m.get("traceability_valid")]

            yield await send_event("progress", {
                "stage": "traceability", "status": "done",
                "message": f"Traceability: {len(matrix) - len(unvalidated)}/{len(matrix)} chains validated",
                "data": {"matrix": matrix, "unvalidated": unvalidated}
            })

            # Step 10: Final result
            result = AnalysisResult(
                app_name=app_name,
                app_id=app_id or "uploaded",
                analysis_goal=request.analysis_goal,
                total_reviews_collected=len(reviews),
                total_reviews_after_cleaning=len(unique_reviews),
                reviews=[r if isinstance(r, Review) else Review(**r) for r in reviews[:50]],
                cleaned_reviews=cleaned[:50],
                findings=findings,
                prd=prd,
                test_cases=test_cases,
                traceability_matrix=matrix,
                data_limitations=(
                    f"Data sourced from iTunes RSS Feed (max ~500 recent reviews). "
                    f"Total collected: {len(reviews)}, after cleaning: {len(unique_reviews)}. "
                    f"LLM-driven analysis: {'Yes' if is_llm_configured() else 'No (fallback rule-based)'}."
                ),
                model_info={
                    "configured": is_llm_configured(),
                    "model": get_llm_config()["model"] if is_llm_configured() else None,
                    "analysis_type": "model-driven" if is_llm_configured() else "rule-based-fallback",
                },
                timestamp=datetime.now().isoformat(),
            )

            yield await send_event("complete", {"result": result.model_dump()})

        except Exception as e:
            yield await send_event("error", {"message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/")
async def index():
    """Serve the frontend."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": "Frontend not found. Please build the frontend."})


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
