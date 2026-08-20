"""
Review collector - fetches reviews from iTunes RSS API.

Data source: Apple iTunes RSS Feed
URL: https://itunes.apple.com/us/rss/customerreviews/...
This is the official Apple RSS feed for App Store reviews, not page scraping.

Limitations:
- Returns at most 500 reviews per page (JSON feed supports up to 500).
- Reviews are sorted by most recent.
- Some reviews may lack body text (title-only reviews).
- Rate limiting: Apple does not publish official limits, but we add delays.
"""
import re
import time
import httpx
from typing import Optional
from .models import Review
from .config import config

ITUNES_RSS_BASE = "https://itunes.apple.com/us/rss/customerreviews"


def extract_app_id(url: str) -> Optional[str]:
    """Extract the numeric App Store ID from an App Store URL."""
    match = re.search(r'/id(\d+)', url)
    if match:
        return match.group(1)
    # fallback: pure numeric
    if url.strip().isdigit():
        return url.strip()
    return None


def fetch_app_info(app_id: str) -> dict:
    """Fetch basic app metadata from iTunes lookup API."""
    url = f"https://itunes.apple.com/lookup?id={app_id}"
    try:
        resp = httpx.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("resultCount", 0) > 0:
            result = data["results"][0]
            return {
                "trackName": result.get("trackName", ""),
                "sellerName": result.get("sellerName", ""),
                "version": result.get("version", ""),
            }
    except Exception:
        pass
    return {}


def fetch_reviews(app_id: str, max_reviews: int = 200) -> list[Review]:
    """
    Fetch reviews from iTunes RSS API.

    Uses paginated JSON feed. Each page returns up to 50 reviews.
    We iterate pages until we hit max_reviews or run out of data.
    """
    if max_reviews is None:
        max_reviews = config.MAX_REVIEWS

    reviews: list[Review] = []
    page = 1
    seen_ids: set[str] = set()

    while len(reviews) < max_reviews:
        url = (
            f"{ITUNES_RSS_BASE}"
            f"/page={page}/id={app_id}"
            f"/sortby=mostrecent/json"
        )
        try:
            resp = httpx.get(url, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        entries = data.get("feed", {}).get("entry", [])
        if not entries:
            break

        # First entry on page 1 is app metadata, skip it
        for entry in entries:
            # App metadata entry has 'im:rating' missing or different structure
            if "im:rating" not in entry:
                continue

            review_id = entry.get("id", {}).get("label", "")
            if not review_id or review_id in seen_ids:
                continue
            seen_ids.add(review_id)

            rating_str = entry.get("im:rating", {}).get("label", "0")
            try:
                rating = int(rating_str)
            except ValueError:
                rating = 0

            review = Review(
                id=review_id,
                author=entry.get("author", {}).get("name", {}).get("label", ""),
                rating=rating,
                title=entry.get("title", {}).get("label", ""),
                body=entry.get("content", {}).get("label", ""),
                version=entry.get("im:version", {}).get("label", ""),
                updated=entry.get("updated", {}).get("label", ""),
            )
            reviews.append(review)

            if len(reviews) >= max_reviews:
                break

        if len(entries) <= 1:
            break

        page += 1
        # Be polite - small delay between requests
        time.sleep(0.5)

    return reviews


def fetch_reviews_from_file(file_path_or_content, filename: str = "") -> list[Review]:
    """
    Load reviews from a JSON or CSV file.
    Accepts either a file path (str) or raw content (bytes) with filename.
    Expected JSON format: array of objects with fields:
      id, author, rating, title, body, version, updated
    Expected CSV format: same fields as columns.
    """
    import json
    import csv
    import io

    reviews: list[Review] = []

    # Determine if input is a path (str) or raw content (bytes)
    if isinstance(file_path_or_content, bytes):
        text = file_path_or_content.decode("utf-8", errors="replace")
        fname = filename
    else:
        with open(file_path_or_content, "r", encoding="utf-8") as f:
            text = f.read()
        fname = file_path_or_content

    if fname.endswith(".json"):
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                reviews.append(Review(
                    id=str(item.get("id", "")),
                    author=item.get("author", ""),
                    rating=int(item.get("rating", 0)),
                    title=item.get("title", ""),
                    body=item.get("body", ""),
                    version=item.get("version", ""),
                    updated=item.get("updated"),
                ))
    elif fname.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            reviews.append(Review(
                id=str(row.get("id", "")),
                author=row.get("author", ""),
                rating=int(row.get("rating", 0) or 0),
                title=row.get("title", ""),
                body=row.get("body", ""),
                version=row.get("version", ""),
                updated=row.get("updated"),
            ))

    return reviews
