"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Model used for the two LLM-backed tools.
_MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokenize the query into lowercase words for keyword matching.
    query_tokens = [t for t in re.split(r"[^a-z0-9]+", description.lower()) if t]

    size_query = size.lower().strip() if size else None

    scored: list[tuple[int, dict]] = []
    for item in listings:
        # --- hard filters --------------------------------------------------
        if max_price is not None and item["price"] > max_price:
            continue

        if size_query is not None and not _size_matches(size_query, item["size"]):
            continue

        # --- relevance score ----------------------------------------------
        score = _score_listing(query_tokens, item)
        if score == 0:
            continue  # no keyword overlap → not relevant

        scored.append((score, item))

    # Highest score first. Python's sort is stable, so equal scores keep
    # their original dataset order.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored]


def _size_matches(size_query: str, listing_size: str) -> bool:
    """
    Lenient, case-insensitive size match against the free-form listing size.

    A listing matches if the requested size token appears in its size string
    (so "M" matches "S/M" and "M/L"), or if the listing is a one-size /
    oversized item that fits broadly.
    """
    listing_lower = listing_size.lower()
    if size_query in listing_lower:
        return True
    if "one size" in listing_lower or "oversized" in listing_lower:
        return True
    return False


def _score_listing(query_tokens: list[str], item: dict) -> int:
    """
    Score a listing by how many query tokens appear in its searchable text.

    Matches in the title and style_tags count double, since those are the
    strongest relevance signals.
    """
    strong_text = " ".join(
        [item["title"]] + item["style_tags"] + item["colors"] + [item["category"]]
    ).lower()
    weak_text = item["description"].lower()

    score = 0
    for token in query_tokens:
        if token in strong_text:
            score += 2
        elif token in weak_text:
            score += 1
    return score


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item.get('title', 'an item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe → general styling advice, no specific pieces invented.
        prompt = (
            f"A user is considering buying this secondhand item: {item_desc}.\n"
            "They have not added any wardrobe items yet. Suggest 1-2 general "
            "outfit ideas for this piece — what kinds of items pair well with it "
            "and what vibe it suits. Keep it to 2-3 sentences, and end by "
            "encouraging them to add their wardrobe for tailored pairings."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it.get('name', it.get('id'))} "
            f"(category: {it.get('category', '?')}, "
            f"colors: {', '.join(it.get('colors', []))}, "
            f"style: {', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            f"A user is considering buying this secondhand item: {item_desc}.\n\n"
            f"Their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with specific "
            "pieces from their wardrobe, referring to those pieces by name. "
            "Include one concrete styling tip (how to layer, tuck, or roll it). "
            "Keep it to 2-4 sentences."
        )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: an empty / whitespace-only outfit means there's nothing to caption.
    if not outfit or not outfit.strip():
        return (
            "Couldn't generate a fit card — no outfit suggestion was provided. "
            "Try styling the item first."
        )

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    platform = new_item.get("platform", "a resale app")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"

    prompt = (
        "Write a short, casual outfit caption (2-4 sentences) for a thrift find, "
        "like a real OOTD post — NOT a product description.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Mention the item name, price, and platform naturally (once each). "
        "Capture the outfit vibe in specific terms. Sound authentic and a little "
        "excited. Lowercase, casual voice, an emoji or two is fine."
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,  # higher temp → varied captions on repeat calls
    )
    return response.choices[0].message.content.strip()
