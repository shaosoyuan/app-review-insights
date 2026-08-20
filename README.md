# App Review Insights

> LLM-powered App Store review analysis pipeline: collect → clean → classify → analyze → PRD → test cases

## Overview

This tool transforms raw App Store reviews into actionable product insights using a combination of deterministic data processing and LLM-driven semantic analysis.

**Live Demo:** Run locally (see Quick Start below)

## Pipeline Architecture

```
App Store Reviews (iTunes RSS API)
        │
        ▼
   ┌─────────┐
   │ Collect  │  iTunes RSS Feed → structured Review objects
   └────┬─────┘
        │
        ▼
   ┌─────────┐
   │  Clean  │  Dedup (content hash) → Normalize → Language detect
   └────┬─────┘
        │
        ▼
   ┌─────────┐
   │ Analyze │  ★ LLM-driven: topic discovery, issue consolidation, evidence grounding
   └────┬─────┘
        │
        ▼
   ┌─────────┐
   │   PRD   │  ★ LLM-driven: findings → requirements → version plan
   └────┬─────┘
        │
        ▼
   ┌──────────┐
   │ Test Cases│ ★ LLM-driven: requirements → test cases with source review excerpts
   └──────────┘
```

### Why LLM for specific steps?

| Step | Method | Rationale |
|------|--------|-----------|
| Data Collection | Deterministic | iTunes RSS API is a well-defined data source |
| Cleaning & Dedup | Deterministic | Set operations on content hashes, field normalization |
| **Review Analysis** | **LLM-driven** | Requires natural language understanding, sarcasm detection, implicit complaint inference |
| **PRD Generation** | **LLM-driven** | Requires creative synthesis and prioritization reasoning |
| **Test Case Generation** | **LLM-driven** | Requires understanding of requirement semantics and edge case reasoning |

## Key Features

### 1. Evidence-Grounded Analysis
Every finding includes:
- `source_review_ids`: Direct links to the reviews that support it
- `source_excerpts`: Quoted text from those reviews
- `confidence`: 0.0-1.0 score indicating evidence strength
- `conflicting_evidence`: Any contradictory feedback

### 2. Traceability Validation
The pipeline validates the full chain: `review → finding → requirement → test case`
- Detects broken links
- Flags unsupported conclusions (findings without source reviews)
- Computes a traceability score

### 3. Hallucination Mitigation
- Low temperature (0.3) for deterministic LLM output
- Explicit prompts requiring source review IDs
- Confidence scoring required for each finding
- Post-analysis validation of all traceability links
- Rule-based fallback when LLM is unavailable

### 4. Graceful Degradation
When no LLM API key is configured, the system falls back to:
- Statistical analysis (rating distribution, version correlation)
- Rule-based PRD generation (severity-based prioritization)
- Template-based test case generation

All fallback outputs are clearly labeled with `is_model_generated: false`.

## Quick Start

### Prerequisites
- Python 3.10+
- An LLM API key (optional, but recommended for full functionality)

### Installation

```bash
# Clone the repository
git clone https://github.com/retro-labs/app-review-insights.git
cd app-review-insights

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment (optional - works without LLM key in fallback mode)
cp .env.example .env
# Edit .env to add your LLM API key
```

### Running the Application

```bash
# Start the backend server
cd backend
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` in your browser. The frontend is served by FastAPI's static file middleware.

Or open `frontend/index.html` directly — it connects to `localhost:8000` by default.

### Using the Application

1. **Enter an App Store URL** (e.g., `https://apps.apple.com/us/app/whatsapp-messenger/id310633997`)
2. **Click "Analyze"** — the pipeline runs with real-time SSE progress updates
3. **Or click "Try Sample"** — runs the full pipeline on bundled sample data

## Configuration

Environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | API key for LLM (OpenAI/DeepSeek/Qwen compatible) | (none - fallback mode) |
| `OPENAI_BASE_URL` | Base URL for API | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | Model name | `gpt-4o-mini` |
| `MAX_REVIEWS_PER_PAGE` | Reviews per RSS page | 50 |
| `MAX_REVIEW_PAGES` | Max pages to fetch | 10 |
| `API_HOST` | Server host | `0.0.0.0` |
| `API_PORT` | Server port | `8000` |

### Supported LLM Providers

Any OpenAI-compatible API:
- OpenAI (GPT-4o, GPT-4o-mini)
- DeepSeek
- Qwen (DashScope)
- Local models via Ollama or LM Studio

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API info |
| GET | `/api/health` | Health check & model status |
| POST | `/api/collect` | Collect reviews from App Store |
| POST | `/api/collect/upload` | Upload JSON/CSV file with reviews |
| POST | `/api/analyze` | Run analysis (non-streaming) |
| GET | `/api/analyze/stream` | Run analysis with SSE progress |
| GET | `/api/results/{job_id}` | Get results by job ID |
| GET | `/api/sample` | Get sample data for demo |

## Project Structure

```
app-review-insights/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app with SSE streaming
│   ├── config.py            # Environment configuration
│   ├── models.py            # Pydantic data models with traceability
│   ├── collector.py         # iTunes RSS API review collection
│   ├── cleaner.py           # Dedup & normalization (deterministic)
│   ├── analyzer.py          # LLM-driven analysis, PRD, test cases
│   └── requirements.txt
├── frontend/
│   └── index.html           # Single-page UI with SSE progress
├── data/
│   └── sample_reviews.json  # Sample data for demo
├── .env.example
├── .gitignore
└── README.md
```

## Data Source

Reviews are collected from the official **iTunes RSS API**:
```
https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/page={page}
```

This is a public, official API that does not require authentication.

## Evaluation Criteria Coverage

| Criterion | Implementation |
|-----------|---------------|
| Data Collection | iTunes RSS API, file upload (JSON/CSV) |
| Data Cleaning | Content-hash dedup, text normalization, language detection |
| Review Classification | LLM-driven dynamic topic discovery (no predefined categories) |
| Issue Analysis | Evidence-grounded findings with source review IDs |
| PRD Generation | LLM-driven requirements with version planning |
| Test Case Generation | LLM-driven test cases linked to requirements and source reviews |
| Vibe Coding | Full-stack app with real-time SSE progress |
| LLM Integration | OpenAI-compatible API with graceful fallback |
| Source Tracing | Full traceability: review → finding → requirement → test case |
| Hallucination Mitigation | Low temperature, source citation, confidence scoring, validation |
