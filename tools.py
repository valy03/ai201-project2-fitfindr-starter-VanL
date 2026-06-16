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

# Default Groq chat model used by the LLM-backed tools.
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


def _chat(prompt: str, temperature: float = 0.7) -> str:
    """Send a single-turn prompt to the Groq chat model and return the text."""
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


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

    # Tokenize the description into lowercase keywords for scoring.
    keywords = re.findall(r"[a-z0-9]+", description.lower())

    results = []
    for listing in listings:
        # Price filter (inclusive) — skip when no ceiling given.
        if max_price is not None and listing["price"] > max_price:
            continue

        # Size filter — case-insensitive substring, e.g. "M" matches "S/M".
        # Skipped entirely when size is None.
        if size is not None and size.strip().lower() not in listing["size"].lower():
            continue

        # Relevance score: how many description keywords appear in the
        # listing's combined searchable text (title + description + tags).
        haystack = " ".join(
            [listing["title"], listing["description"], " ".join(listing["style_tags"])]
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        if score > 0:
            results.append((score, listing))

    # Highest score first; sorted() is stable so dataset order breaks ties.
    results.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in results]


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
    item_line = (
        f"{new_item['title']} — {new_item['category']}, "
        f"colors: {', '.join(new_item['colors'])}, "
        f"style: {', '.join(new_item['style_tags'])}."
    )

    items = wardrobe.get("items", [])

    if not items:
        # No wardrobe — give general styling advice for the item alone.
        prompt = (
            "You are a thrift-fashion stylist. The user is considering this "
            f"second-hand find:\n\n{item_line}\n\n"
            "They haven't shared their wardrobe yet. Suggest 1-2 complete outfits "
            "around this piece, naming the kinds of items that pair well (tops, "
            "bottoms, shoes, layers), the colors that work, and the overall vibe. "
            "Note that this advice is based on the item alone since no wardrobe was "
            "provided. Keep it to a short, friendly paragraph or two."
        )
    else:
        # Format the user's wardrobe so the model can name specific pieces.
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it['category']}; "
            f"colors: {', '.join(it['colors'])}; "
            f"style: {', '.join(it['style_tags'])})"
            for it in items
        )
        prompt = (
            "You are a thrift-fashion stylist. The user is considering this "
            f"second-hand find:\n\n{item_line}\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with SPECIFIC "
            "pieces from their wardrobe (refer to them by name). For each outfit, "
            "give a one-line styling rationale (the vibe, how to wear it). Keep it "
            "short and friendly."
        )

    return _chat(prompt, temperature=0.7)


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
    # Replace this with your implementation
    return ""
