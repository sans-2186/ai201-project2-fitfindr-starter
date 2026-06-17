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
Looks through the mock listings (loaded with `load_listings()`) and returns the ones that match what the user typed plus any hard filters they gave (size, max price), with the best match first.

**Input parameters:**
- `description` (str, required): what the user wants, e.g. `"vintage graphic tee"`. Checked case-insensitively against each listing's `title`, `description`, `style_tags`, `colors`, and `category`.
- `size` (str, optional, default `None`): a size like `"M"`. The sizes in the data are messy (`"M"`, `"S/M"`, `"W30 L30"`, `"One Size"`), so I match loosely — a listing passes if its size string contains what was asked for, or if it's a one-size / oversized piece. `None` means don't filter on size.
- `max_price` (float, optional, default `None`): a price cap; a listing only passes if `price <= max_price`. `None` means don't filter on price.

**What it returns:**
A `list[dict]` of matching listings. Each one is a full listing record with all the dataset fields: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. The list is sorted by relevance (how many query words hit across the searched fields), highest first. If nothing matches, it returns an empty list `[]`.

**What happens if it fails or returns nothing:**
It just returns `[]` — it doesn't raise an exception for "no matches." The planning loop notices the empty list, puts a helpful message in the session telling the user how to loosen things up (raise `max_price`, drop a tag, or remove the size filter), and stops there **without** calling `suggest_outfit` or `create_fit_card`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the listing it just found and the user's wardrobe and writes a short styling idea that pairs the new item with stuff the user already owns, plus one concrete tip for how to wear it.

**Input parameters:**
- `new_item` (dict): one listing record (usually `results[0]` from `search_listings`). It uses the `title`, `category`, `colors`, `style_tags`, and `condition`.
- `wardrobe` (dict): the user's closet in the wardrobe-schema format — a dict with an `"items"` key holding a list, where each item has `id`, `name`, `category`, `colors`, `style_tags`, and an optional `notes`. Comes from `get_example_wardrobe()` (full) or `get_empty_wardrobe()` (empty).

**What it returns:**
A non-empty `str` (a few sentences) with the styling suggestion, naming actual wardrobe pieces and one styling tip, e.g. *"Wear this with your baggy dark-wash jeans and chunky white sneakers; layer the black denim jacket over it and half-tuck the front for shape."* This one calls the LLM (Groq `llama-3.3-70b-versatile`) to write the text from the item + wardrobe, going for complementary categories (a top → suggest bottoms, shoes, outerwear) and overlapping colors/styles.

**What happens if it fails or returns nothing:**
If the wardrobe is empty (new user), it doesn't make up clothes — it gives general advice for the item on its own and tells the user to add wardrobe items for better pairings. It's still a real, non-empty string, so no crash, and the loop keeps going to `create_fit_card`.

---

### Tool 3: create_fit_card

**What it does:**
Turns the listing and the styling suggestion into a short, casual caption (a "fit card") the user could actually post — naming the item, what it cost and where, and the vibe of the look.

**Input parameters:**
- `outfit` (str): the styling string from `suggest_outfit`.
- `new_item` (dict): the chosen listing, used for the details that go in the caption — `title`, `price`, and `platform`.

**What it returns:**
A `str` — a couple sentences in a casual, lowercase voice, e.g. *"scored this faded tour tee off depop for $24 🖤 made for my baggy jeans + chunky sneaks — full fit in stories."* It works in the item name, price, and platform once each. I run the LLM at a higher temperature here so the caption comes out different each time instead of repeating.

**What happens if it fails or returns nothing:**
If `outfit` is empty or just whitespace, it skips the LLM entirely and returns a plain error string (like *"Couldn't generate a fit card — no outfit suggestion was provided."*) instead of crashing or making something up. The loop also only gets here when there's a selected item and a real outfit suggestion to begin with.

---

### Additional Tools (if any)

None for the core build. (Stretch idea: `add_to_wardrobe(item)` to let the user save the purchased piece back into their wardrobe for future suggestions.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

It runs the tools in order, but with guards that can cut it short depending on what each tool gives back. It works off the parsed request (description, optional size, optional max_price) and the session, going step by step:

1. **Parse the request** into `description`, `size`, `max_price` (via `_parse_query`). Store the dict in `session["parsed"]`.
2. **Call `search_listings(description, size, max_price)`** and store the list in `session["search_results"]`.
   - `if search_results == []`: set `session["error"] = "<no-match message with how to loosen the query>"` and **return early** — do not call any further tool.
   - `else`: continue.
3. **Select** the top result: `session["selected_item"] = session["search_results"][0]`.
4. **Call `suggest_outfit(new_item=session["selected_item"], wardrobe=session["wardrobe"])`** and store the string in `session["outfit_suggestion"]`.
   - If `wardrobe["items"] == []`, the tool itself returns a "style it solo + add wardrobe items" suggestion — still a non-empty string, so the loop continues.
5. **Guard before the fit card:** `if session["selected_item"] and (session["outfit_suggestion"] or "").strip()`:
   - **Call `create_fit_card(outfit=session["outfit_suggestion"], new_item=session["selected_item"])`** and store `session["fit_card"]`.
   - `else`: skip — `fit_card` stays `None`.
6. **Done** when either an error short-circuited the loop (step 2) or `fit_card` is set. Return `session`.

The key thing is it never moves on with empty or junk input from the step before — each call depends on what the last one returned.

---

## State Management

**How does information from one tool get passed to the next?**

Everything goes through one `session` dict that's created per request. The loop writes each tool's output into it and reads from it to build the next tool's input. The tools themselves don't touch any shared state — they just take arguments and hand back a value. What's tracked:

- `query` — the raw user query string.
- `parsed` — `{description, size, max_price}` extracted from the query.
- `wardrobe` — the user's wardrobe dict (from `get_example_wardrobe()` / `get_empty_wardrobe()`), set once at session start.
- `search_results` / `selected_item` — the list returned by `search_listings` and the chosen top result (`search_results[0]`).
- `outfit_suggestion` — the suggestion string returned by `suggest_outfit`.
- `fit_card` — the caption string returned by `create_fit_card`.
- `error` — any user-facing error string set on early exit (else `None`).

The flow: `parsed` feeds `search_listings`, whose top result becomes `selected_item`, which feeds `suggest_outfit` (along with `wardrobe`), whose `outfit_suggestion` feeds `create_fit_card` (along with `selected_item`), giving `fit_card`. At the end the response to the user is built from whatever's in `session`.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | Nothing matches the query | Stop the loop and tell the user, e.g. *"I couldn't find any vintage graphic tees under $30 in size M right now."* Then give them concrete things to try based on the filters they used — *"Try raising your budget above $30, dropping the size filter, or just searching 'graphic tee'."* Don't call `suggest_outfit` or `create_fit_card`. |
| suggest_outfit | The wardrobe is empty | Don't make up clothes. Style the item on its own with a general tip and say something like *"You haven't added any wardrobe items yet — add a few and I can pair this with what you already own."* Keep going to `create_fit_card`, since there's still a real suggestion. |
| create_fit_card | The outfit text is missing or empty | Don't fake a caption. Skip this step and return the listing and styling suggestion you've already got, with a note like *"I found and styled this piece, but couldn't write a fit-card caption — the outfit text came back empty."* |

---

## Architecture

```
User query: "vintage graphic tee under $30, I wear baggy jeans + chunky sneakers"
    │  parse → {description, size, max_price}
    ▼
┌─────────────────────────── Planning Loop ───────────────────────────┐
│                                                                      │
│  ├─► search_listings(description, size, max_price) ──reads── [listings.json]
│  │        │ results == []                                            │
│  │        ├──► [ERROR] session.error =                               │
│  │        │      "No matches — raise budget / drop size / loosen     │
│  │        │       query"  ──► return session  ───────────────────────┼──┐
│  │        │                                                          │  │
│  │        │ results == [item, ...]                                   │  │
│  │        ▼                                                          │  │
│  │   Session: search_results = results; selected_item = results[0]   │  │
│  │        │                                                          │  │
│  ├─► suggest_outfit(selected_item, wardrobe) ──reads── [wardrobe]    │  │
│  │        │  wardrobe.items == []  → "style solo + add items"        │  │
│  │        ▼                                                          │  │
│  │   Session: outfit_suggestion = "<styling text>"                  │  │
│  │        │                                                          │  │
│  │   guard: selected_item AND non-empty outfit_suggestion ?          │  │
│  │        │ no → skip, note "no fit card" ──► return session ────────┼──┤
│  │        │ yes                                                      │  │
│  └─► create_fit_card(outfit_suggestion, selected_item)               │  │
│           │                                                          │  │
│       Session: fit_card = "<caption>"                                │  │
│           │                                            error paths ──┼──┘
└───────────┼──────────────────────────────────────────────────────────┘
            ▼
   Render session → user sees: listing + styling suggestion + fit-card caption
```

(Session state is the shared store the loop reads/writes at every step; tools are pure functions taking inputs and returning values.)

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

I'm using **Claude (Claude Code)** for all three tools, one at a time.

- **`search_listings`** — I'll give it the *Tool 1* block above (inputs, return shape, failure mode) plus the field list from `utils/data_loader.py`, and ask it to write the function on top of `load_listings()`: match `description` case-insensitively across `title/description/style_tags/colors/category`, do the lenient `size` match and the `max_price` cap, and sort by relevance. To check it: read the code to make sure it filters on all three params, handles `size=None`/`max_price=None`, and returns `[]` instead of erroring on no match — then run three queries, including a guaranteed miss like `("ball gown", max_price=5)`.
- **`suggest_outfit`** — I'll give it the *Tool 2* block plus the wardrobe schema from `data/wardrobe_schema.json` and ask it to match by complementary category and overlapping colors/styles, returning a string. To check it: run it once with `get_example_wardrobe()` (should name real pieces) and once with `get_empty_wardrobe()` (should fall back to the "style it solo / add items" message and still return a real string).
- **`create_fit_card`** — I'll give it the *Tool 3* block and ask for a caption string built from the outfit text and the listing's `title/price/platform`. To check it: make sure the caption actually has the right price and platform, and that it returns an error string (no LLM call) when `outfit` is empty.

**Milestone 4 — Planning loop and state management:**

I'll hand **Claude** the *Planning Loop*, *State Management*, *Error Handling*, and *Architecture* sections together and ask it to build the loop as a function that fills in and returns the `session` dict, calling the three tools in order with the early-exit guards. To check it: walk it through the *A Complete Interaction* example and confirm the happy path goes `selected_item → outfit_suggestion → fit_card`, the empty-results path sets `session["error"]` and bails before `suggest_outfit`, and the empty-wardrobe path still reaches `create_fit_card`. I'll test all three before touching the Gradio UI.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr needs to do (in my own words):**
FitFindr is a secondhand-shopping helper. The user describes a piece they want (plus optional size and price limits), it finds matching thrift listings, styles the best one against the clothes they already own, and writes a short social-media caption for the look. The request kicks off `search_listings`; if that finds at least one thing, the top result goes into `suggest_outfit` with the wardrobe, and that suggestion goes into `create_fit_card`. If the search comes back empty, FitFindr stops and tells the user how to loosen their query instead of running the later tools on nothing — and similarly it falls back to general advice if the wardrobe is empty and skips the fit card if there's no outfit text.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Search:** The user's request triggers `search_listings("vintage graphic tee", max_price=30.0)`. The dataset has two strong matches under $30 (`lst_002` Y2K Butterfly Baby Tee — $18, and `lst_006` 2003 Tour Bootleg Graphic Tee — $24); results come back sorted by relevance to "vintage graphic tee." FitFindr picks the top result, e.g. `lst_006` "Graphic Tee — 2003 Tour Bootleg Style — $24, Depop, Good condition."

**Step 2 — Suggest outfit:** Because Step 1 returned at least one listing, FitFindr calls `suggest_outfit(new_item=<lst_006 tee>, wardrobe=<user's wardrobe>)`. Using the example wardrobe it returns something like: "Wear this with your baggy dark-wash jeans (`w_001`) and chunky white sneakers (`w_007`); throw the vintage black denim jacket (`w_006`) over the top for a 90s streetwear look. Half-tuck the front for shape."

**Step 3 — Fit card:** FitFindr calls `create_fit_card(outfit=<suggestion>, new_item=<lst_006 tee>)`, which returns a short caption: "scored this faded tour tee off depop for $24 🖤 made for my baggy jeans + chunky sneaks — full fit in stories."

**Final output to user:** The user sees the chosen listing (title, price, platform, condition), the styling suggestion built from their own wardrobe, and the ready-to-post fit-card caption. **Error path:** if `search_listings` had returned no results, the user would instead see a message like "No vintage graphic tees under $30 right now — try raising your budget or dropping the 'vintage' tag," and FitFindr would stop without calling `suggest_outfit` or `create_fit_card`.
