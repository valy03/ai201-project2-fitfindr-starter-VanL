# FitFindr

FitFindr is a small agent that helps you shop secondhand. You describe what you
want in plain English; it searches a mock listings dataset, picks the best match,
styles it against your wardrobe, and writes a shareable "fit card" caption for the
find. It runs as a Gradio web app.

```
You: "vintage graphic tee under $30, size M"
   → finds the best-matching listing
   → suggests an outfit using pieces you already own
   → writes an OOTD-style caption you could actually post
```

---

## Setup

```bash
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the project root (free key at
[console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Running it

**Web app (Gradio):**
```bash
python app.py
```
Open the URL printed in your terminal (usually http://localhost:7860, but check
the output — the port can differ). Enter a query, pick a wardrobe, hit **Find it**.

**Command line (smoke test of the agent loop):**
```bash
python agent.py
```

**Tests:**
```bash
pytest -q
```

---

## Architecture at a glance

```
User query + wardrobe
      │
      ▼
  run_agent  (agent.py)  ◄── reads/writes ──►  session dict
      │
      ├─ parse query        → session["parsed"]
      ├─ search_listings()  → session["search_results"]
      │     └─ empty? → set session["error"], RETURN early
      ├─ select results[0]  → session["selected_item"]
      ├─ suggest_outfit()   → session["outfit_suggestion"]
      └─ create_fit_card()  → session["fit_card"]
      │
      ▼
  app.py handle_query maps the session to 3 UI panels
```

The LLM-backed tools call Groq's `llama-3.3-70b-versatile`. The search tool is
pure Python over the local dataset — no LLM.

---

## Tool inventory

### 1. `search_listings(description, size, max_price) -> list[dict]`

- **Purpose:** find listings in `data/listings.json` that match the user's intent.
  This is the only non-LLM tool — deterministic keyword scoring.
- **Inputs:**
  - `description` (`str`) — keywords describing the item, e.g. `"vintage graphic tee"`.
  - `size` (`str | None`) — case-insensitive substring filter (e.g. `"M"` matches
    `"S/M"`). `None` skips the size filter.
  - `max_price` (`float | None`) — inclusive price ceiling. `None` skips the price filter.
- **Output:** a `list[dict]` of matching listings sorted by relevance (best first).
  Each dict has `id`, `title`, `description`, `category`, `style_tags`, `size`,
  `condition`, `price`, `colors`, `brand`, `platform`. Listings whose keyword-overlap
  score is 0 are dropped. Returns `[]` if nothing matches — it never raises.

### 2. `suggest_outfit(new_item, wardrobe) -> str`

- **Purpose:** style the found item into 1–2 complete outfits, naming specific pieces
  the user already owns.
- **Inputs:**
  - `new_item` (`dict`) — a listing dict (the item being considered), same shape
    `search_listings` returns.
  - `wardrobe` (`dict`) — a wardrobe with an `"items"` key holding a list of item
    dicts. May be empty.
- **Output:** a non-empty `str`. With a populated wardrobe it references real pieces
  by name; with an empty wardrobe it returns general styling advice for the item alone.

### 3. `create_fit_card(outfit, new_item) -> str`

- **Purpose:** write a short, casual OOTD-style caption for the find.
- **Inputs:**
  - `outfit` (`str`) — the suggestion string from `suggest_outfit`.
  - `new_item` (`dict`) — the listing dict, used for name/price/platform.
- **Output:** a 2–4 sentence `str` caption that mentions the item name, price, and
  platform once each. Generated at temperature 1.0 so repeated runs on the same input
  produce different captions. If `outfit` is empty/whitespace, returns a descriptive
  error string instead of calling the LLM.

---

## How the planning loop works (the decisions the agent makes)

`run_agent(query, wardrobe)` in `agent.py` is a **fixed pipeline with one branch**.
The three tools have a strict data dependency — each consumes the previous tool's
output — so the order isn't chosen dynamically; it's fixed. The only place the
agent's behavior *changes* is the empty-search gate. Here is what it actually decides:

1. **Parse the query.** `_parse_query` extracts three things from the raw text:
   - `max_price` — a regex looks for a `$`-number or an "under N" phrase. **Decision:**
     if none is found, `max_price` stays `None` and the price filter is skipped entirely
     (rather than defaulting to some arbitrary cap that would silently hide listings).
   - `size` — matches an explicit `"size M"` phrase, otherwise a standalone size token
     (XXS/XS/S/M/L/XL/XXL), longest-first so `"XL"` wins over `"L"`, and only on word
     boundaries so the `M` in "Medium" doesn't trigger. **Decision:** no size found →
     `None` → no size filter.
   - `description` — whatever text is left after stripping the price/size phrases.

2. **Search, then decide whether to continue.** It calls
   `search_listings(description, size, max_price)`. **This is the one real decision
   point:**
   - **If the result list is empty,** the agent sets `session["error"]` to a message
     that echoes *what it searched and what to change*, and **returns immediately**.
     It does **not** call `suggest_outfit` or `create_fit_card` — there's no item to
     style, so calling them would be meaningless (and would feed empty input into the
     LLM). This is the core "don't proceed on bad input" decision.
   - **Otherwise,** it selects `search_results[0]` as `selected_item`. The list is
     already sorted by relevance, so the top element is the best match — the agent
     picks one item and commits to it rather than asking the user to choose.

3. **Suggest an outfit.** Calls `suggest_outfit(selected_item, wardrobe)`. **There is
   deliberately no branch here for an empty wardrobe** — that case is handled *inside*
   the tool (it returns general advice), so the loop always proceeds. The agent treats
   "no wardrobe" as a normal situation, not an error.

4. **Create the fit card.** Calls `create_fit_card(outfit_suggestion, selected_item)`
   and stores the result.

5. **Return the session.**

**How it knows it's done:** the loop is finished when either `session["fit_card"]` is
set (success) or `session["error"]` is set (early exit at step 2). The caller checks
`error` first to tell the two apart.

---

## State management

There is no global state and nothing is re-derived or re-prompted between steps. A
single `session` dict, created by `_new_session(query, wardrobe)`, is the single
source of truth for one interaction. Each step writes its output to a named field;
the next step reads its input from that field.

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | caller | parse step |
| `parsed` (description / size / max_price) | parse step | search step |
| `search_results` | search step | empty-check + select step |
| `selected_item` | select step | suggest step **and** card step |
| `wardrobe` | caller | suggest step |
| `outfit_suggestion` | suggest step | card step |
| `fit_card` | card step | final return |
| `error` | search step (on early exit) | caller (checked first) |

On success, `error` stays `None` and `fit_card` holds the caption. On the no-results
exit, `error` holds the message and `outfit_suggestion`/`fit_card` stay `None`.

**Verified, not assumed:** I confirmed state flows by *object identity* (not by value)
— the exact same `selected_item` dict object that's stored in the session is the one
passed into both `suggest_outfit` and `create_fit_card`, and the `outfit_suggestion`
string returned by `suggest_outfit` is the identical object handed to
`create_fit_card`. If the agent were re-prompting or substituting hardcoded values
between steps, those identity checks would fail. They pass.

`app.py`'s `handle_query` reads the finished session and maps it to the three UI
panels: on error it puts the message in the first panel and leaves the other two
blank; on success it formats `selected_item` into a readable listing block and returns
the outfit suggestion and fit card alongside it.

---

## Error handling per tool

Each failure mode was triggered deliberately (Milestone 5), not just hoped to work.

| Tool | Failure mode | What the agent does |
|------|-------------|---------------------|
| `search_listings` | No listing matches | Returns `[]` (never raises). The loop catches the empty list, sets a specific `error`, and stops before the LLM tools. |
| `suggest_outfit` | Wardrobe is empty | Not treated as an error — the tool returns general, item-only styling advice. The loop continues normally. |
| `create_fit_card` | `outfit` is empty/whitespace | Returns a descriptive error string (with the item details so the user can still style it) instead of raising. No LLM call is made. |

**Concrete examples from testing:**

*Search, no results* — running the impossible query end-to-end:
```
$ python agent.py
...
Error message: I couldn't find any listings matching 'designer ballgown' in size XXS
under $5 right now. Try raising your max price, dropping the size filter, or using
broader keywords.
```
Note this isn't a bare "no results found" — it names the query, the size, and the
price it tried, and offers three concrete next steps. `session["fit_card"]` is `None`
and `suggest_outfit` is never called.

*Empty wardrobe* —
```
$ python -c "from tools import search_listings, suggest_outfit; \
from utils.data_loader import get_empty_wardrobe; \
r = search_listings('vintage graphic tee', None, 50); \
print(suggest_outfit(r[0], get_empty_wardrobe()))"
→ "I'm so excited about this Y2K baby tee find. Based on its adorable butterfly
   print and pastel colors, I'd suggest pairing it with high-waisted light-washed
   jeans or a flowy neutral skirt... canvas sneakers to keep it casual..."
```
A useful styling paragraph, not an exception or an empty string.

*Empty outfit into the fit card* —
```
$ python -c "from tools import search_listings, create_fit_card; \
r = search_listings('vintage graphic tee', None, 50); print(create_fit_card('', r[0]))"
→ "Couldn't create a fit card — no outfit suggestion was provided. Here's the item
   so you can style it yourself: Y2K Baby Tee — Butterfly Print — $18, depop."
```

These paths are also locked in by the test suite (`test_search_empty_results`,
`test_suggest_outfit_empty_wardrobe_does_not_crash`,
`test_create_fit_card_empty_outfit_returns_error_string`,
`test_run_agent_no_results_early_exit`), so a regression fails CI.

---

## Testing

`tests/test_tools.py` has 18 tests. The pure-Python search tool is tested directly.
The two LLM-backed tools and the agent loop are tested with the Groq call
monkeypatched out, so the suite is fast, offline, and deterministic — it asserts on
control flow and prompt contents, not on exact LLM wording. The real LLM calls were
verified separately with manual live smoke tests (and via the running Gradio app).

```bash
pytest -q          # 18 passed
```

---

## AI usage

I used Claude (in Claude Code) throughout, driven by the specs in `planning.md`.
Two concrete instances:

**1. Implementing `search_listings`.**
*Input I gave it:* the Tool 1 block from `planning.md` (the three parameters with
types, the return-shape field list, the "score by keyword overlap, drop score-0,
sort high-to-low" rule, and the "return `[]`, never raise" failure mode), plus the
`load_listings()` docstring so it wouldn't re-implement file loading.
*What it produced:* a function that filtered by `max_price` and `size` only when those
args were non-`None`, scored listings by counting how many description keywords
appeared in the combined title/description/style_tags text, dropped zero-score
listings, and returned them sorted.
*What I changed/overrode:* the first cut did size matching as a plain case-insensitive
substring, which is what my spec literally said. I kept that for the dataset's slash
sizes like `"S/M"`, but I verified with three queries (a real match, a nonsense query,
and a no-filter query) before trusting it — confirming the nonsense query returned
`[]` rather than throwing. I also added explicit tests for the price filter and the
empty-results case rather than assuming the generated code handled them.

**2. Implementing the planning loop `run_agent`.**
*Input I gave it:* the Planning Loop section (the numbered branch logic), the State
Management table, the architecture diagram, and the `_new_session` field list from
`agent.py`.
*What it produced:* a `run_agent` that parsed the query, called the three tools in
order, wrote each result into its session field, and returned early with `error` set
when search came back empty.
*What I changed/overrode:* the parsing was the part I scrutinized most. The initial
size regex would match the `M` inside words like "Medium," so I had it switch to
word-boundary matching and check size tokens longest-first (so `"XL"` isn't shadowed
by `"L"`). I also made the no-results `error` message echo the actual parsed query,
size, and price instead of a generic string, because Milestone 5 specifically required
the agent to tell the user *what* failed and *what to try*. I verified the whole loop
by object identity to be sure state was really flowing between tools and the agent
wasn't re-prompting or using hardcoded values between steps.

---

## Spec reflection

Writing `planning.md` first paid off most in the planning loop. Because the tool
contracts (inputs, return types, and especially the failure modes) were pinned down
before any code existed, each tool could be built and tested in isolation, and the
loop became almost mechanical to wire up — the hard decisions (when to stop, what's
an error vs. a normal case) were already made on paper.

The biggest gap between spec and reality was query parsing. The spec said "regex for
a size token," which sounds trivial, but real queries like "vintage tee, medium wash"
exposed false matches the spec hadn't anticipated — the spec assumed parsing was easy
and it was the fiddliest part. The other refinement was the *quality* of the
no-results message: my first error string was generic, and testing the failure path
deliberately (rather than just confirming it didn't crash) is what pushed it to name
the specific query and offer concrete next steps. The lesson: a spec is good at
defining the happy path and the data contracts, but the failure messages and the
messy input handling only get sharp once you actually trigger them.
