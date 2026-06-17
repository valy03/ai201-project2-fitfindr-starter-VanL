"""
Unit tests for the FitFindr tools.

Each tool is tested in isolation with hardcoded inputs, with at least one test
per failure mode described in planning.md. Tools are implemented and tested one
at a time — tests for a tool are added only after that tool is implemented.

Run with:  pytest -q
"""

import tools
from tools import search_listings, suggest_outfit, create_fit_card
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


# ── Tool 3: create_fit_card ──────────────────────────────────────────────────

def test_create_fit_card_returns_caption(monkeypatch):
    """Happy path: returns a non-empty caption string."""
    _patch_chat(monkeypatch)
    result = create_fit_card("Pair it with baggy jeans and boots.", SAMPLE_ITEM)
    assert isinstance(result, str)
    assert result.strip() != ""


def test_create_fit_card_includes_item_details_in_prompt(monkeypatch):
    """The item name, price, and platform are passed to the LLM."""
    captured = _patch_chat(monkeypatch)
    create_fit_card("Pair it with baggy jeans and boots.", SAMPLE_ITEM)
    prompt = captured[0]
    assert "Faded Band Tee" in prompt
    assert "22" in prompt          # price
    assert "depop" in prompt       # platform


def test_create_fit_card_uses_high_temperature(monkeypatch):
    """Captions should vary between runs — verify a high temperature is used."""
    temps = []

    def fake_chat(prompt, temperature=0.7):
        temps.append(temperature)
        return "caption"

    monkeypatch.setattr(tools, "_chat", fake_chat)
    create_fit_card("Pair it with baggy jeans and boots.", SAMPLE_ITEM)
    assert temps[0] >= 0.9


def test_create_fit_card_empty_outfit_returns_error_string(monkeypatch):
    """Failure mode: empty/whitespace outfit returns an error string, no API call."""
    captured = _patch_chat(monkeypatch)
    for bad in ["", "   ", "\n\t"]:
        result = create_fit_card(bad, SAMPLE_ITEM)
        assert isinstance(result, str)
        assert result.strip() != ""
        assert "Faded Band Tee" in result   # item details offered instead
    # The guard returns before ever calling the LLM.
    assert captured == []


# ── Planning loop: agent.run_agent ───────────────────────────────────────────
#
# The loop calls the two LLM-backed tools, so we patch them in agent's namespace
# to keep these tests offline and deterministic. We assert on control flow and
# state, not on caption wording.

import agent
from agent import run_agent, _parse_query


def _patch_agent_llm(monkeypatch):
    """Stub suggest_outfit and create_fit_card as imported into agent.py."""
    monkeypatch.setattr(agent, "suggest_outfit", lambda item, wardrobe: "FAKE OUTFIT")
    monkeypatch.setattr(agent, "create_fit_card", lambda outfit, item: "FAKE CARD")


def test_parse_query_extracts_size_and_price():
    parsed = _parse_query("vintage graphic tee under $30 size M")
    assert parsed["size"] == "M"
    assert parsed["max_price"] == 30.0
    assert "tee" in parsed["description"]
    # The price/size phrases are stripped out of the description.
    assert "$30" not in parsed["description"]
    assert "size M" not in parsed["description"]


def test_parse_query_no_filters():
    parsed = _parse_query("denim jacket")
    assert parsed["size"] is None
    assert parsed["max_price"] is None
    assert parsed["description"] == "denim jacket"


def test_run_agent_happy_path(monkeypatch):
    """Full success path: all fields populated, no error."""
    _patch_agent_llm(monkeypatch)
    session = run_agent("vintage graphic tee under $50", get_example_wardrobe())
    assert session["error"] is None
    assert session["selected_item"] is not None
    assert session["outfit_suggestion"] == "FAKE OUTFIT"
    assert session["fit_card"] == "FAKE CARD"


def test_run_agent_no_results_early_exit(monkeypatch):
    """No-results gate: error set, LLM tools never reached."""
    called = {"suggest": False, "card": False}

    def boom_suggest(item, wardrobe):
        called["suggest"] = True
        return "should not happen"

    def boom_card(outfit, item):
        called["card"] = True
        return "should not happen"

    monkeypatch.setattr(agent, "suggest_outfit", boom_suggest)
    monkeypatch.setattr(agent, "create_fit_card", boom_card)

    session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
    assert session["error"] is not None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None
    assert called == {"suggest": False, "card": False}


def test_run_agent_empty_wardrobe_still_completes(monkeypatch):
    """Empty wardrobe is not an error — loop runs to completion."""
    _patch_agent_llm(monkeypatch)
    session = run_agent("vintage graphic tee under $50", get_empty_wardrobe())
    assert session["error"] is None
    assert session["fit_card"] == "FAKE CARD"
