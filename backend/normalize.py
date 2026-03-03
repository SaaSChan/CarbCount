"""Query normalization for consistent cache matching."""

import re


def normalize_query(query: str) -> str:
    """
    Normalize a food query for cache key matching.

    Rules:
      - Lowercase
      - Strip leading/trailing whitespace
      - Collapse multiple spaces to single space
      - Sort comma-separated items (order independence)
      - Remove common filler words that don't affect nutrition

    "Chicken, Rice, Beans" == "beans, chicken, rice"
    "Two slices of  pepperoni pizza" == "two slices of pepperoni pizza"
    """
    # Lowercase and strip
    normalized = query.lower().strip()

    # Collapse whitespace
    normalized = re.sub(r'\s+', ' ', normalized)

    # Sort comma-separated items for order independence
    if ',' in normalized:
        parts = [p.strip() for p in normalized.split(',')]
        parts = [p for p in parts if p]  # Remove empty parts
        normalized = ', '.join(sorted(parts))

    return normalized
