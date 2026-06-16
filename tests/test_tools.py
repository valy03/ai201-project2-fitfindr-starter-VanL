"""
Unit tests for the FitFindr tools.

Each tool is tested in isolation with hardcoded inputs, with at least one test
per failure mode described in planning.md. Tools are implemented and tested one
at a time — tests for a tool are added only after that tool is implemented.

Run with:  pytest -q
"""

import tools
from tools import search_listings, suggest_outfit
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# A minimal listing dict reused across the LLM-backed tool tests.
SAMPLE_ITEM = {
    "id": "lst_test",
    "title": "Faded Band Tee",
    "description": "Soft vintage band tee, perfectly worn in.",
    "category": "tops",
    "style_tags": ["vintage", "graphic tee", "grunge"],
    "size": "M",
    "condition": "good",
    "price": 22.0,
    "colors": ["black", "white"],
    "brand": None,
    "platform": "depop",
}


# ── Tool 1: search_listings ─────────────────────────────────────────────────

def test_search_returns_results():
    """Happy path: a relevant query returns a non-empty list of dicts."""
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(item, dict) for item in results)


def test_search_empty_results():
    """Failure mode: no match returns an empty list, not an exception."""
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    """max_price is an inclusive ceiling — nothing above it comes back."""
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    """size matching is case-insensitive substring: 'm' matches 'S/M', 'M'."""
    results = search_listings("tee", size="m", max_price=None)
    assert len(results) > 0
    assert all("m" in item["size"].lower() for item in results)


def test_search_no_filters_returns_keyword_matches():
    """With size=None and max_price=None, keyword matching still applies."""
    results = search_listings("denim", size=None, max_price=None)
    assert len(results) > 0
    # Every result should actually relate to the keyword somewhere in its text.
    for item in results:
        haystack = (
            item["title"] + item["description"] + " ".join(item["style_tags"])
        ).lower()
        assert "denim" in haystack


def test_search_sorted_by_relevance():
    """Results are sorted by descending keyword-overlap score."""
    results = search_listings("vintage denim jacket", size=None, max_price=None)
    assert len(results) > 1

    def score(item):
        haystack = (
            item["title"] + item["description"] + " ".join(item["style_tags"])
        ).lower()
        return sum(kw in haystack for kw in ["vintage", "denim", "jacket"])

    scores = [score(item) for item in results]
    assert scores == sorted(scores, reverse=True)


# ── Tool 2: suggest_outfit ───────────────────────────────────────────────────
#
# suggest_outfit calls the Groq LLM via tools._chat. To keep tests fast,
# offline, and deterministic, we monkeypatch _chat with a fake that records the
# prompt it was given and returns a canned string. That lets us assert on the
# tool's branching logic (what it puts in the prompt) without a real API call.

def _patch_chat(monkeypatch):
    """Replace tools._chat with a recorder; returns the list of captured prompts."""
    captured = []

    def fake_chat(prompt, temperature=0.7):
        captured.append(prompt)
        return "Fake outfit suggestion."

    monkeypatch.setattr(tools, "_chat", fake_chat)
    return captured


def test_suggest_outfit_returns_nonempty_string(monkeypatch):
    """Happy path: returns a non-empty string for a populated wardrobe."""
    _patch_chat(monkeypatch)
    result = suggest_outfit(SAMPLE_ITEM, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


def test_suggest_outfit_names_specific_wardrobe_pieces(monkeypatch):
    """With a real wardrobe, the prompt references specific owned pieces."""
    captured = _patch_chat(monkeypatch)
    suggest_outfit(SAMPLE_ITEM, get_example_wardrobe())
    prompt = captured[0]
    # A few known example-wardrobe item names should be in the prompt.
    assert "Chunky white sneakers" in prompt
    assert "Baggy straight-leg jeans, dark wash" in prompt


def test_suggest_outfit_empty_wardrobe_does_not_crash(monkeypatch):
    """Failure mode: empty wardrobe still returns a non-empty string."""
    captured = _patch_chat(monkeypatch)
    result = suggest_outfit(SAMPLE_ITEM, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""
    # The empty-wardrobe branch asks for general, item-only advice.
    assert "haven't shared their wardrobe" in captured[0]
