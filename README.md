# App Review Insights

Turn real App Store user reviews into executable product plans — from data collection to PRD and test cases, powered by LLM-driven semantic analysis.

## Features

- **Data Collection**: Fetches reviews from the iTunes RSS Feed API (public, no API key required)
- **Review Cleaning**: Deduplication (exact + fuzzy matching), text normalization, language detection
- **LLM-Driven Analysis**: Dynamic topic discovery, issue consolidation, and evidence-grounded findings
- **PRD Generation**: Product requirements document with version planning, priorities, and traceability
- **Test Case Generation**: Test cases linked to requirements and source user reviews
- **Traceability Validation**: Full chain from reviews -> findings -> requirements -> test cases
- **File Import**: Supports JSON and CSV review data upload
- **Fallback Mode**: Works without LLM configuration using rule-based analysis

## Quick Start

### Prerequisites

- Python 3.10+
- An OpenAI-compatible API key (optional but recommended for full LLM-driven analysis)

### Installation

```bash
git clone https://github.com/shaosoyuan/app-review-insights.git
cd app-review-insights

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your API key
```

### Running

```bash
cd backend
python main.py
```

The application will be available at `http://127.0.0.1:8000`.

## Usage

1. **Enter an App Store URL**: Paste any US App Store app link
2. **Set Analysis Goal** (optional): e.g., "subscription conversion", "low-rating reviews"
3. **Click "Start Analysis"**: Watch the execution progress in real-time
4. **Review Results**: Browse Reviews, Findings, PRD, Test Cases, and Traceability tabs

### Uploading Custom Data

Click the upload area to import a `.json` or `.csv` file with review data.

**JSON format:**
```json
[
  {
    "review_id": "12345",
    "author": "JohnDoe",
    "rating": 4,
    "title": "Great app",
    "content": "Really helpful for workouts...",
    "version": "7.3.1",
    "date": "2024-01-15"
  }
]
```

**CSV format:** Columns: `review_id, author, rating, title, content, version, date`

## Architecture

```
app-review-insights/
├── backend/
│   ├── main.py          # FastAPI server with SSE streaming
│   ├── models.py        # Pydantic data models
│   ├── collector.py     # iTunes RSS Feed API client
│   ├── cleaner.py       # Review cleaning & deduplication
│   └── analyzer.py      # LLM-driven analysis engine
├── frontend/
│   ├── index.html       # Single-page UI
│   └── sample_reviews.json  # Sample data for static serving
├── data/
│   ├── cache/           # Runtime review cache
│   └── sample/          # Sample data (canonical copy)
├── requirements.txt
├── .env.example
├── run.sh               # Quick start script
└── README.md
```

## Data Collection Method

Reviews are fetched from the **iTunes RSS Customer Reviews Feed**:

```
https://itunes.apple.com/{country}/rss/customerreviews/page={n}/id={appId}/sortby=mostrecent/json
```

- **Source**: Apple's public RSS feed (no authentication required)
- **Limitation**: Provides up to ~500 most recent reviews (10 pages x ~50 per page)
- **Coverage**: US App Store by default
- **Rate limit**: Respectful request timing with built-in delays

App metadata is fetched from the iTunes Lookup API:
```
https://itunes.apple.com/lookup?id={appId}
```

## LLM Configuration

Supports any OpenAI-compatible API:

| Provider | Base URL | Model Example |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

Configure in `.env`:
```env
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

### Anti-Hallucination Measures

- LLM is instructed to only use review IDs and excerpts from provided data
- Every finding includes source review IDs for verification
- Confidence scores and uncertainty markers are required
- Conflicting evidence is explicitly noted
- Rule-based fallback when LLM is unavailable or fails

## Tech Stack

- **Backend**: Python, FastAPI, httpx, OpenAI SDK
- **Frontend**: HTML, CSS, JavaScript (vanilla, no build step)
- **Data Source**: iTunes RSS Feed API
- **LLM**: Any OpenAI-compatible API

## License

MIT
