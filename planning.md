# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Searches the mock listings dataset for items matching a keyword description, with optional size and price-ceiling filters. Returns the matching listings sorted by relevance (best match first).

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): keywords describing what the user wants (e.g., "vintage graphic tee").
- `size` (str | None): size to filter by; case-insensitive (e.g., "M" matches "S/M"). `None` skips size filtering.
- `max_price` (float | None): inclusive max price. `None` skips price filtering.

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
A `list[dict]` of matching listings sorted by relevance score (highest first). Each listing dict has: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Scoring is by keyword overlap between `description` and each listing's text; listings scoring 0 are dropped.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
The tool itself returns an empty list `[]` — it never raises. Handling the empty case is the agent loop's job: when search returns `[]`, the agent sets a helpful error message (suggest relaxing the price or broadening keywords) and stops. It does **not** call `suggest_outfit` with empty input.
---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Given a thrifted item and the user's wardrobe, asks the LLM to suggest 1–2 complete outfits that pair the new item with specific pieces the user already owns.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): a listing dict (the item the user is considering buying) — same shape returned by `search_listings`.
- `wardrobe` (dict): a wardrobe dict with an `'items'` key holding a list of wardrobe item dicts. May be empty.

**What it returns:**
<!-- Describe the return value -->
A non-empty `str` with outfit suggestions, naming specific wardrobe pieces alongside the new item and giving a short styling rationale.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If `wardrobe['items']` is empty, the tool does not fail — it returns general styling advice for the item alone (what kinds of pieces pair well, what vibe it suits) instead of raising or returning an empty string. The agent only reaches this tool after a real item is found, so it always has valid `new_item` input.
---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Generates a short, shareable OOTD-style caption for the thrifted find, combining the item details and the suggested outfit into something that reads like a real social post (not a product description).

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): the outfit suggestion string returned by `suggest_outfit`.
- `new_item` (dict): the listing dict for the thrifted item (used for name, price, platform).

**What it returns:**
<!-- Describe the return value -->
A 2–4 sentence `str` caption that mentions the item name, price, and platform once each naturally, captures the outfit vibe in specific terms, and varies between runs.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
If `outfit` is empty or whitespace-only, the tool returns a descriptive error-message string rather than raising. In practice the agent only calls this after `suggest_outfit` returns a non-empty string, so this is a defensive guard.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

The tools have a strict data dependency — each consumes the previous tool's output — so the order is fixed. The only place behavior branches is the empty-search gate. Here is the exact conditional logic, specific enough to implement directly:

1. **Initialize:** `session = _new_session(query, wardrobe)`.

2. **Parse the query** into `description`, `size`, `max_price`; store the three in `session["parsed"]`.
   - `max_price`: regex for a `$`-number or an "under N" phrase. If none found, `max_price = None`.
   - `size`: match a known size token (XS/S/M/L/XL or a "size X" phrase). If none found, `size = None`.
   - `description`: the remaining keyword text from the query.

3. **Call `search_listings(description, size, max_price)`** and store the return value in `session["search_results"]`.
   - **IF `search_results` is empty (`len == 0`):** set `session["error"]` to a helpful message and `return session` immediately — do **not** call `suggest_outfit` or `create_fit_card`.
   - **ELSE:** set `session["selected_item"] = search_results[0]` (top result, already relevance-sorted) and continue to step 4.

4. **Call `suggest_outfit(session["selected_item"], session["wardrobe"])`** and store the string in `session["outfit_suggestion"]`. No branch here — if the wardrobe is empty, the tool returns general styling advice, so the loop always proceeds.

5. **Call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`** and store the string in `session["fit_card"]`.

6. **`return session`.**

The loop is done when `session["fit_card"]` is set (success, reached step 6) or `session["error"]` is set (early exit at step 3). The caller checks `session["error"]` first to tell the two apart.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

A single `session` dict (built by `_new_session`) is the single source of truth for one interaction. Each step writes its output into a named field; the next step reads its inputs from those fields. Nothing is passed by globals or re-derived.

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | caller | parse step |
| `parsed` (description / size / max_price) | parse step | search step |
| `search_results` | search step | empty-check + select step |
| `selected_item` | select step | suggest step + card step |
| `wardrobe` | caller | suggest step |
| `outfit_suggestion` | suggest step | card step |
| `fit_card` | card step | final return |
| `error` | step 3 on early exit | caller (checked first) |

On success, `error` stays `None` and `fit_card` holds the result. On the no-results early exit, `error` holds the message and `outfit_suggestion` / `fit_card` stay `None`.
---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Tool returns `[]`. Agent sets `session["error"]` to a concrete, actionable message that echoes what it searched and what to change — e.g. *"I couldn't find any vintage graphic tees under $30 in size M right now. Try raising your max price, dropping the size filter, or using broader keywords like 'graphic tee'."* — then returns early. It does **not** call `suggest_outfit`, and offers no fit card. |
| suggest_outfit | Wardrobe is empty | Not treated as an error. The tool detects `wardrobe['items'] == []` and returns general styling advice for the item alone (item types and colors that pair well, the vibe it suits), and the message tells the user it based the styling on the item only because no wardrobe was provided. The loop continues to `create_fit_card` normally. |
| create_fit_card | Outfit input is missing or incomplete | Tool guards an empty/whitespace `outfit` and returns a descriptive string instead of raising — e.g. *"I couldn't build a fit card because no outfit suggestion was provided. Here's the item so you can style it yourself: <title> — $<price>, <platform>."* The agent shows that to the user with the item details rather than a bare error. |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

```
User query  +  wardrobe
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Planning Loop  (run_agent)          ◄──── reads/writes ────► SESSION dict │
│                                                          { query, parsed,  │
│  1. parse query                                            search_results, │
│        │  writes parsed{description,size,max_price}        selected_item,   │
│        ▼                                                   wardrobe,        │
│  2. search_listings(description, size, max_price)          outfit_suggestion│
│        │  writes search_results                            fit_card, error }│
│        │                                                                   │
│        ├── results == []  ─►  SESSION: error = "No listings found…"        │
│        │                          │                                        │
│        │                          └────────────────────────► return ──┐    │
│        │                                                               │    │
│        │  results = [item, …]                                          │    │
│        ▼                                                               │    │
│     SESSION: selected_item = results[0]                                │    │
│        │                                                               │    │
│  3. suggest_outfit(selected_item, wardrobe)                            │    │
│        │  (empty wardrobe → general advice, no branch)                 │    │
│        ▼                                                               │    │
│     SESSION: outfit_suggestion = "…"                                   │    │
│        │                                                               │    │
│  4. create_fit_card(outfit_suggestion, selected_item)                  │    │
│        │                                                               │    │
│        ▼                                                               │    │
│     SESSION: fit_card = "…"                                            │    │
│        │                                                               │    │
│        └───────────────────────► return  ◄────── error path returns ──┘    │
└─────────────────────────────────────────────────────────────────────────┘
     │
     ▼
User sees:  error message (early exit)   OR   fit card + outfit (success)
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

- **`search_listings`** — I'll use Claude. Input: the Tool 1 block above (inputs, return shape, scoring rule, empty-list failure mode) plus the `load_listings()` docstring from `utils/data_loader.py`. Expected output: a function that loads listings, filters by `max_price` and case-insensitive `size` only when those args are non-`None`, scores remaining listings by keyword overlap between `description` and the title/description/style_tags, drops score-0 listings, and returns them sorted high-to-low. Verify before trusting: read the code to confirm all three params are applied and that no-match returns `[]` (not an exception), then run 3 queries — (a) "vintage graphic tee" under $30 size M should return matches, (b) a nonsense query should return `[]`, (c) a query with `size=None, max_price=None` should still return keyword matches.

- **`suggest_outfit`** — I'll use Claude. Input: the Tool 2 block plus one example listing dict and `get_example_wardrobe()` output so it knows the wardrobe shape (`{'items': [...]}`). Expected output: a function that branches on `wardrobe['items']` being empty, builds a Groq prompt naming specific wardrobe pieces (or general advice if empty), and returns a non-empty string. Verify: run once with the example wardrobe (output should name real wardrobe items) and once with `get_empty_wardrobe()` (output should give general advice and never be empty or raise).

- **`create_fit_card`** — I'll use Claude. Input: the Tool 3 block plus a sample `outfit` string and listing dict. Expected output: a function that guards empty `outfit`, otherwise calls Groq with a higher temperature for a 2–4 sentence casual caption mentioning name/price/platform once each. Verify: run twice with the same input and confirm the captions differ (temperature working), confirm name/price/platform appear, and pass `outfit=""` to confirm it returns an error string rather than raising.

**Milestone 4 — Planning loop and state management:**

- **`run_agent` + parsing** — I'll use Claude. Input: the Planning Loop section (the numbered branch logic), the State Management table, the Architecture diagram, and the `_new_session` field list from `agent.py`. Expected output: an implementation of `run_agent` that parses the query into `session["parsed"]`, calls the three tools in order, writes each result to its session field, and returns early with `session["error"]` set when `search_listings` returns `[]`. Verify: run the two cases already in `agent.py`'s `__main__` — the graphic-tee query should fill `selected_item`/`outfit_suggestion`/`fit_card` with `error is None`, and the "designer ballgown size XXS under $5" query should set `error` and leave the output fields `None`. I'll confirm the no-results path never reaches `suggest_outfit` (e.g. by checking `outfit_suggestion is None`).

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse, then search.**
<!-- What does the agent do first? Which tool is called? With what input? -->
The loop parses the query into `parsed = {description: "vintage graphic tee", size: None, max_price: 30.0}` (no size token appears in the query, so `size` stays `None`; "under $30" gives `max_price=30.0`). It then calls:

`search_listings(description="vintage graphic tee", size=None, max_price=30.0)`

This returns a relevance-sorted `list[dict]` of matching listings, e.g. `[{id, title: "Faded Band Tee", price: 22.0, size: "M", platform: "depop", style_tags: [...], …}, …]`, stored in `session["search_results"]`. Because the list is non-empty, the agent sets `session["selected_item"] = search_results[0]` (the Faded Band Tee) and continues.

*(If the list had been empty, the agent would set `session["error"]` with a relax-your-filters message and return here — `suggest_outfit` would never run.)*

**Step 2 — Suggest an outfit.**
<!-- What happens next? What was returned from step 1? What tool is called now? -->
Using the selected item from step 1, the agent calls:

`suggest_outfit(new_item=<Faded Band Tee dict>, wardrobe=<user's wardrobe>)`

The tool sees a non-empty wardrobe and asks the LLM to style the tee with specific owned pieces, returning a string like *"Pair this with your wide-leg jeans and platform Docs for a 90s grunge look. Roll the sleeves once and tuck the front corner for shape."* — stored in `session["outfit_suggestion"]`.

**Step 3 — Create the fit card.**
<!-- Continue until the full interaction is complete -->
The agent passes the outfit string and the same item dict to:

`create_fit_card(outfit=<suggestion>, new_item=<Faded Band Tee dict>)`

The tool returns a casual caption mentioning the item, price, and platform once each, stored in `session["fit_card"]`, e.g. *"thrifted this faded band tee off depop for $22 and honestly it was made for my wide-legs 🖤 full look in my stories"*.

**Final output to user:**
<!-- What does the user actually see at the end? -->
`session["error"]` is `None`, so the user sees the found item ("Faded Band Tee — $22, depop, good condition"), the styling suggestion from step 2, and the shareable fit-card caption from step 3. On the no-results path instead, the user would see only the helpful error message and no outfit or card.