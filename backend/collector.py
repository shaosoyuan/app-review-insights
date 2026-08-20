"""
Review collector - fetches App Store reviews via iTunes RSS Feed API.

Data Source: Apple iTunes RSS Feed (public, no API key required)
Endpoint: https://itunes.apple.com/{country}/rss/customerreviews/page={n}/id={appId}/sortby=mostrecent/json
Limitation: RSS feed provides up to 10 pages x ~50 reviews = ~500 most recent reviews per app.
"""
import httpx
import re
import json
from models import Review
from typing import Optional


def extract_app_id(url: str) -> Optional[str]:
    """Extract the App Store app ID from a URL or raw ID string."""
    if url.isdigit():
        return url.strip()
    match = re.search(r'/id(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'(\d{8,})', url)
    if match:
        return match.group(1)
    return None


async def fetch_app_info(app_id: str) -> dict:
    """Fetch app metadata from iTunes Lookup API."""
    url = f"https://itunes.apple.com/lookup?id={app_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        if data.get("resultCount", 0) > 0:
            return data["results"][0]
    return {}


async def fetch_reviews(app_id: str, country: str = "us", max_pages: int = 10) -> list[Review]:
    """
    Fetch reviews from iTunes RSS Feed API.
    
    Args:
        app_id: The numeric App Store app ID
        country: App Store country code (default: us)
        max_pages: Maximum pages to fetch (each page ~50 reviews)
    
    Returns:
        List of Review objects
    
    Data source: https://itunes.apple.com/{country}/rss/customerreviews/
    Limitation: Only the most recent ~500 reviews are available via RSS.
    """
    reviews = []
    seen_ids = set()
    
    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(1, max_pages + 1):
            url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews/"
                f"page={page}/id={app_id}/sortby=mostrecent/json"
            )
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    break
                
                data = resp.json()
                entries = data.get("feed", {}).get("entry", [])
                
                if not entries:
                    break
                
                # First entry is app metadata, skip it
                for entry in entries[1:] if page == 1 else entries:
                    review_id = entry.get("id", {}).get("label", "")
                    if not review_id or review_id in seen_ids:
                        continue
                    seen_ids.add(review_id)
                    
                    review = Review(
                        review_id=review_id,
                        author=entry.get("author", {}).get("name", {}).get("label", ""),
                        rating=int(entry.get("im:rating", {}).get("label", "0")),
                        title=entry.get("title", {}).get("label", ""),
                        content=entry.get("content", {}).get("label", ""),
                        version=entry.get("im:version", {}).get("label", ""),
                        date=entry.get("updated", {}).get("label", ""),
                    )
                    reviews.append(review)
            except Exception:
                continue
    
    return reviews


def load_reviews_from_json(file_path: str) -> list[Review]:
    """Load reviews from a JSON file. Expected format: list of objects with review_id, author, rating, title, content, version, date."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if isinstance(data, dict) and "reviews" in data:
        data = data["reviews"]
    
    reviews = []
    for item in data:
        reviews.append(Review(
            review_id=str(item.get("review_id", item.get("id", ""))),
            author=item.get("author", ""),
            rating=int(item.get("rating", 0)),
            title=item.get("title", ""),
            content=item.get("content", item.get("body", "")),
            version=item.get("version", ""),
            date=item.get("date", ""),
        ))
    return reviews


def load_reviews_from_csv(file_path: str) -> list[Review]:
    """Load reviews from a CSV file. Expected columns: review_id, author, rating, title, content, version, date."""
    import csv
    reviews = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            reviews.append(Review(
                review_id=str(row.get("review_id", row.get("id", ""))),
                author=row.get("author", ""),
                rating=int(row.get("rating", 0)),
                title=row.get("title", ""),
                content=row.get("content", row.get("body", "")),
                version=row.get("version", ""),
                date=row.get("date", ""),
            ))
    return reviews
