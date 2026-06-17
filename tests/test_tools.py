"""
Tests for the three FitFindr tools, exercised in isolation.

Run with:  pytest tests/

The two LLM-backed tools (suggest_outfit, create_fit_card) need a live
GROQ_API_KEY. Those tests are skipped automatically when no key is set, so the
non-LLM logic and failure-mode guards still run everywhere.
"""

import os
import sys

import pytest

# Make the project root importable when pytest is run from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

HAS_GROQ = bool(os.environ.get("GROQ_API_KEY"))
needs_groq = pytest.mark.skipif(not HAS_GROQ, reason="GROQ_API_KEY not set")


# ── search_listings ────────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Nonsense query + impossible price → empty list, never an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_is_lenient():
    # "M" should match listings whose size string contains it (e.g. "S/M").
    results = search_listings("tee", size="M", max_price=None)
    for item in results:
        s = item["size"].lower()
        assert "m" in s or "one size" in s or "oversized" in s


def test_search_results_sorted_by_relevance():
    results = search_listings("vintage denim jacket", size=None, max_price=None)
    # Re-score is internal; here we just assert the top result is denim/jacket-ish.
    assert len(results) > 0
    top = results[0]
    haystack = (top["title"] + " " + " ".join(top["style_tags"])).lower()
    assert "denim" in haystack or "jacket" in haystack


# ── suggest_outfit ───────────────────────────────────────────────────────────

@needs_groq
def test_suggest_outfit_with_wardrobe():
    item = search_listings("graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str) and out.strip()


@needs_groq
def test_suggest_outfit_empty_wardrobe_does_not_crash():
    item = search_listings("graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    # Failure mode: empty wardrobe → still a non-empty string, no exception.
    assert isinstance(out, str) and out.strip()


# ── create_fit_card ──────────────────────────────────────────────────────────

def test_fit_card_empty_outfit_returns_message_not_exception():
    # Failure mode: empty outfit must return an error string, not raise.
    item = {"title": "Test Tee", "price": 20.0, "platform": "depop"}
    msg = create_fit_card("", item)
    assert isinstance(msg, str) and msg.strip()
    assert "couldn't" in msg.lower() or "no outfit" in msg.lower()


def test_fit_card_whitespace_outfit_guarded():
    item = {"title": "Test Tee", "price": 20.0, "platform": "depop"}
    msg = create_fit_card("   \n  ", item)
    assert isinstance(msg, str) and msg.strip()


@needs_groq
def test_fit_card_generates_caption():
    item = search_listings("graphic tee", size=None, max_price=50)[0]
    outfit = "Pair it with baggy jeans and chunky sneakers."
    card = create_fit_card(outfit, item)
    assert isinstance(card, str) and card.strip()
