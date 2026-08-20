"""
Review cleaner - deduplication, normalization, and structuring.

This module uses deterministic rules (not LLM) because:
- Deduplication is a well-defined set operation on review IDs and content hashes.
- Field normalization is deterministic (trim whitespace, unify dates, detect language).
- These operations must be reproducible and deterministic per the requirements.
"""
import hashlib
import re
from typing import Optional
from .models import Review


def normalize_text(text: str) -> str:
    """Normalize whitespace and strip control characters."""
    if not text:
        return ""
    # Remove control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def detect_language_simple(text: str) -> str:
    """
    Simple language detection based on character ranges.
    Uses Unicode block detection - deterministic, no external dependency.
    """
    if not text:
        return "unknown"
    # Check for CJK characters
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_count > len(text) * 0.3:
        return "zh"
    # Check for Cyrillic
    cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04ff')
    if cyrillic_count > len(text) * 0.3:
        return "ru"
    # Check for Arabic
    arabic_count = sum(1 for c in text if '\u0600' <= c <= '\u06ff')
    if arabic_count > len(text) * 0.3:
        return "ar"
    # Default to English
    return "en"


def content_hash(review: Review) -> str:
    """Generate a hash of the review's normalized title + body for dedup."""
    combined = normalize_text(review.title.lower() + " " + review.body.lower())
    return hashlib.md5(combined.encode("utf-8")).hexdigest()


def clean_reviews(reviews: list[Review]) -> tuple[list[Review], int]:
    """
    Clean, deduplicate, and structure reviews.

    Returns (cleaned_reviews, duplicates_removed_count).
    """
    if not reviews:
        return [], 0

    seen_hashes: dict[str, str] = {}  # hash -> first review id
    duplicates = 0

    for review in reviews:
        # Normalize fields
        review.title = normalize_text(review.title)
        review.body = normalize_text(review.body)
        review.author = normalize_text(review.author)
        review.cleaned_body = review.body

        # Detect language
        combined_text = review.title + " " + review.body
        review.language = detect_language_simple(combined_text)

        # Deduplicate by content hash
        h = content_hash(review)
        if h in seen_hashes:
            review.is_duplicate = True
            review.duplicate_of = seen_hashes[h]
            duplicates += 1
        else:
            seen_hashes[h] = review.id
            review.is_duplicate = False

    # Filter out empty reviews (no title and no body)
    cleaned = [r for r in reviews if not r.is_duplicate and (r.title or r.body)]

    return cleaned, duplicates


def get_rating_distribution(reviews: list[Review]) -> dict:
    """Compute deterministic rating distribution statistics."""
    if not reviews:
        return {}
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in reviews:
        if 1 <= r.rating <= 5:
            dist[r.rating] += 1
    total = len(reviews)
    return {
        "distribution": dist,
        "total": total,
        "average": round(sum(r.rating for r in reviews) / total, 2) if total else 0,
        "low_rating_count": dist[1] + dist[2],
        "low_rating_percentage": round((dist[1] + dist[2]) / total * 100, 1) if total else 0,
    }


def get_version_distribution(reviews: list[Review]) -> dict:
    """Compute deterministic version distribution."""
    if not reviews:
        return {}
    versions: dict[str, int] = {}
    for r in reviews:
        v = r.version or "unknown"
        versions[v] = versions.get(v, 0) + 1
    return dict(sorted(versions.items(), key=lambda x: x[1], reverse=True))
