"""
Review cleaner - handles deduplication, normalization, and structuring of raw reviews.

This module uses deterministic rules (not LLM) because:
- Deduplication is a deterministic operation (exact/fuzzy match)
- Field normalization is rule-based
- Language detection uses a lightweight heuristic
"""
from models import Review, CleanedReview
from difflib import SequenceMatcher
from typing import Optional
import re


def detect_language(text: str) -> str:
    """Simple heuristic language detection based on Unicode ranges."""
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
    # Check for Japanese (Hiragana/Katakana)
    jp_count = sum(1 for c in text if '\u3040' <= c <= '\u30ff')
    if jp_count > len(text) * 0.1:
        return "ja"
    # Default to English
    return "en"


def normalize_text(text: str) -> str:
    """Normalize whitespace and trim."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_duplicate(review: Review, seen_reviews: list[Review], threshold: float = 0.85) -> tuple[bool, Optional[str]]:
    """
    Check if a review is a duplicate of one already seen.
    Uses exact content match first, then fuzzy matching.
    
    Returns (is_duplicate, duplicate_of_id)
    """
    content = normalize_text(review.content)
    if not content:
        return True, None  # Empty reviews are treated as duplicates
    
    # Exact match check
    for seen in seen_reviews:
        seen_content = normalize_text(seen.content)
        if content == seen_content:
            return True, seen.review_id
    
    # Fuzzy match for near-duplicates
    for seen in seen_reviews:
        seen_content = normalize_text(seen.content)
        if not seen_content:
            continue
        ratio = SequenceMatcher(None, content.lower(), seen_content.lower()).ratio()
        if ratio >= threshold:
            return True, seen.review_id
    
    return False, None


def clean_reviews(reviews: list[Review]) -> list[CleanedReview]:
    """
    Clean, deduplicate, and structure raw review data.
    
    Steps:
    1. Normalize text fields (trim, collapse whitespace)
    2. Detect language
    3. Deduplicate (exact + fuzzy match)
    4. Calculate content length
    5. Filter out empty reviews
    """
    cleaned = []
    seen_reviews = []
    
    for review in reviews:
        # Normalize
        content = normalize_text(review.content)
        title = normalize_text(review.title)
        
        # Skip empty reviews
        if not content and not title:
            continue
        
        # Deduplicate
        is_dup, dup_of = is_duplicate(review, seen_reviews)
        
        cleaned_review = CleanedReview(
            review_id=review.review_id,
            author=review.author,
            rating=review.rating,
            title=title,
            content=content,
            version=review.version,
            date=review.date,
            content_length=len(content),
            is_duplicate=is_dup,
            duplicate_of=dup_of,
            language=detect_language(content),
        )
        
        cleaned.append(cleaned_review)
        if not is_dup:
            seen_reviews.append(review)
    
    return cleaned


def filter_by_goal(cleaned_reviews: list[CleanedReview], goal: str) -> list[CleanedReview]:
    """
    Filter reviews based on analysis goal/constraint.
    Supports goals like: low-rating, specific version, subscription, etc.
    """
    goal_lower = goal.lower() if goal else ""
    
    if not goal_lower:
        return cleaned_reviews
    
    # Low-rating reviews
    if any(kw in goal_lower for kw in ["low rating", "low-rating", "negative", "1-star", "1 star"]):
        return [r for r in cleaned_reviews if r.rating <= 2 and not r.is_duplicate]
    
    # High-rating reviews
    if any(kw in goal_lower for kw in ["high rating", "positive", "5-star", "5 star", "positive feedback"]):
        return [r for r in cleaned_reviews if r.rating >= 4 and not r.is_duplicate]
    
    # Specific version
    version_match = re.search(r'version\s+([\d.]+)', goal_lower)
    if version_match:
        target_version = version_match.group(1)
        return [r for r in cleaned_reviews if r.version == target_version and not r.is_duplicate]
    
    # Default: return non-duplicate reviews
    return [r for r in cleaned_reviews if not r.is_duplicate]
