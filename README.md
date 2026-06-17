# FitFindr 🛍️

FitFindr is a little secondhand-shopping agent I built for Project 2. You tell it
what you're looking for in normal English, and it finds a thrift listing, figures
out how to style it with clothes you already own, and writes a caption you could
actually post. The part I care about most is that it's a real planning loop: it
looks at what the search comes back with and decides what to do next, instead of
just firing all three tools every time no matter what.

Here's the basic flow:

```
your query → parse it → search_listings → suggest_outfit → create_fit_card → done
                            │
                            └─ nothing found? stop here and tell you what to change
```

## Setup

Install the dependencies:

```bash
pip install -r requirements.txt
```

Then drop your Groq API key into a `.env` file in the project root (you can grab a
free one at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

To run things:

```bash
python app.py        # the Gradio web UI (usually http://localhost:7860)
python agent.py      # runs the happy path and the no-results case in the terminal
pytest tests/        # runs the tests for all three tools
```

## The three tools

All three live in [`tools.py`](tools.py), and each one works on its own so I could
test them before wiring anything together. The descriptions below line up with the
actual function signatures in the code.

### `search_listings(description, size=None, max_price=None) -> list[dict]`

Inputs:
- `description` (`str`) — what you're after, like `"vintage graphic tee"`. It gets
  matched (case-insensitive) against each listing's title, description, style tags,
  colors, and category.
- `size` (`str | None`) — something like `"M"`. I kept the matching loose on purpose,
  since the sizes in the data are all over the place (`"M"`, `"S/M"`, `"W30 L30"`,
  `"One Size"`). A listing passes if its size string contains what you asked for, or
  if it's a one-size / oversized piece. Pass `None` to skip the size filter.
- `max_price` (`float | None`) — a price ceiling; a listing only passes if
  `price <= max_price`. `None` skips it.

Output: a `list[dict]`, where each dict is a full listing record (`id`, `title`,
`description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`,
`brand`, `platform`). The list is sorted so the most relevant match is first — I
score by how many of the query words show up, and I weight hits in the title, style
tags, colors, and category higher than hits buried in the description. If nothing
matches, it returns an empty list `[]`.

Purpose: find and rank the listings that fit what the user asked for. This one is
pure Python, no LLM.

### `suggest_outfit(new_item, wardrobe) -> str`

Inputs:
- `new_item` (`dict`) — a single listing (normally the top search result).
- `wardrobe` (`dict`) — the user's closet, in the form `{"items": [...]}`, where each
  item has `id`, `name`, `category`, `colors`, `style_tags`, and an optional `notes`.

Output: a `str`, a couple sentences suggesting how to wear the new item with specific
pieces the user already owns, plus one concrete styling tip.

Purpose: turn "here's a listing" into "here's an outfit." This one calls the LLM
(Groq `llama-3.3-70b-versatile`) at temperature 0.7.

### `create_fit_card(outfit, new_item) -> str`

Inputs:
- `outfit` (`str`) — the styling text that `suggest_outfit` produced.
- `new_item` (`dict`) — the chosen listing, used for the `title`, `price`, and
  `platform` that go in the caption.

Output: a `str` — a short, casual caption (lowercase, OOTD-post energy) that works
in the item name, price, and platform once each.

Purpose: write the shareable caption. Also an LLM call, but at temperature 0.9 so I
get a different caption each time instead of the same one over and over.

## How the planning loop works

The loop is in `run_agent()` in [`agent.py`](agent.py). It runs the tools in order,
but with guards that can cut it short — and that branching is the whole point.

1. Make a fresh `session` dict.
2. Parse the query with `_parse_query()` (just regex, no LLM call) into
   `{description, size, max_price}` and stash it in `session["parsed"]`.
3. Run `search_listings(...)`. **This is the decision point.** If it comes back
   empty, I write a helpful message into `session["error"]` and return right there —
   `suggest_outfit` and `create_fit_card` never run, and `selected_item`,
   `outfit_suggestion`, and `fit_card` all stay `None`. If it found something, I keep
   going.
4. Grab the top result: `session["selected_item"] = search_results[0]`.
5. Run `suggest_outfit(selected_item, wardrobe)` and save the string.
6. One more guard before the caption: only call `create_fit_card(...)` if there's a
   selected item *and* the outfit string isn't empty. Otherwise skip it.
7. Return the session.

So at each step the thing it checks is the previous tool's output (empty list? empty
string?), and it never asks the user to type anything again mid-run.

## State management

Everything lives in one `session` dict that gets created per request. The loop writes
each tool's result into it and reads from it to build the next tool's input. The tools
themselves don't touch any shared state — they just take arguments and return values.

| Key | Set when | What's in it |
|-----|----------|--------------|
| `query` | start | the raw query string |
| `parsed` | after parsing | `{description, size, max_price}` |
| `search_results` | after `search_listings` | the ranked list of listings |
| `selected_item` | after picking | `search_results[0]` |
| `wardrobe` | start | the user's wardrobe dict |
| `outfit_suggestion` | after `suggest_outfit` | the styling string |
| `fit_card` | after `create_fit_card` | the caption string |
| `error` | only on early exit | the message to show the user (otherwise `None`) |

The chain is: `parsed` → `search_listings` → `selected_item` → `suggest_outfit`
(plus `wardrobe`) → `outfit_suggestion` → `create_fit_card` (plus `selected_item`) →
`fit_card`. Because `selected_item` is just `search_results[0]`, the exact listing the
search returned is the exact one `suggest_outfit` gets — I checked this at runtime and
`session["selected_item"] is session["search_results"][0]` comes back `True`, so it's
literally the same object, no copying or re-typing. The Gradio handler in
[`app.py`](app.py) just reads the finished session and fills in the three panels.

## Error handling

| Tool | What can go wrong | What the agent does |
|------|-------------------|---------------------|
| `search_listings` | nothing matches | Returns `[]` (never throws). The loop catches the empty list, sets `session["error"]`, and stops before any LLM call — and the message tells the user what to actually change (raise the budget, drop the size, loosen the words). |
| `suggest_outfit` | the wardrobe is empty | It doesn't make up clothes the user doesn't have. It gives general styling advice for the item and nudges them to add wardrobe items, still returning a real (non-empty) string, so the loop keeps going. |
| `create_fit_card` | the outfit string is empty/whitespace | It checks for that *before* calling the LLM and returns a plain error string ("Couldn't generate a fit card — no outfit suggestion was provided.") instead of crashing or inventing a caption. |

A real example from my testing: I ran `"designer ballgown size XXS under $5"`, which
parses to `description="designer ballgown", size="XXS", max_price=5.0`. There's
obviously no $5 designer ballgown in the dataset, so the search returned nothing, and
the session came back like this:

```
error: 'No listings matched "designer ballgown". Try raising your budget above $5,
        dropping the size filter, loosening your search terms.'
selected_item:     None
outfit_suggestion: None
fit_card:          None
```

That's the proof the no-results branch both gives a useful message and skips the two
LLM tools entirely. The empty-outfit and empty-wardrobe cases have their own tests in
[`tests/test_tools.py`](tests/test_tools.py).

## Spec reflection

One way the spec helped: writing out the planning loop and error handling in
[`planning.md`](planning.md) before I coded meant the "stop if the search is empty"
branch was baked in from the start. When I got to `run_agent()` I was basically just
translating my own numbered steps into Python, so I didn't have to go back and bolt on
the adaptive behavior later — it was already the design.

One way I diverged: in my first draft of the spec I had `suggest_outfit` and
`create_fit_card` returning structured dicts (stuff like `{text, paired_item_ids}` and
`{caption}`). But the function stubs in the starter — and `agent.py`, which treats
those values as strings — expected plain strings, so I switched the tools to return
strings and updated planning.md to match. I lost the machine-readable list of matched
wardrobe item IDs that a fancier UI could've used, but since both the CLI and the
Gradio panels just display text anyway, the string was the right fit here.

## How I used AI

I leaned on Claude (through Claude Code) while building this, working off my own specs
in planning.md.

1. **Writing `search_listings`.** I gave it my Tool 1 spec and asked it to implement
   the search using `load_listings()` — filter by price and by a lenient size match,
   score by keyword overlap, drop the zero-score listings, and sort by relevance. The
   first version scored every field equally, which meant a search for "vintage graphic
   tee" floated up anything that just said "vintage" somewhere in its description. I
   changed the scoring so hits in the title, style tags, colors, and category count
   double, which pushed actual graphic tees to the top. I also double-checked it
   returns `[]` instead of throwing when nothing matches, and tested it on three
   queries including a deliberate miss.

2. **Writing the planning loop in `run_agent()`.** I handed it the planning loop,
   state management, and architecture sections and asked for the loop with the
   early-exit on empty search results. The thing I overrode was query parsing — it
   reached for an LLM call to pull out the size/price, and I swapped that for plain
   regex (`_parse_query`) so parsing stays fast, free, and predictable. I also added
   the guard before `create_fit_card` and confirmed at runtime that `selected_item` is
   the same object as `search_results[0]`.

## The data

- `data/listings.json` — 40 fake secondhand listings across tops, bottoms, outerwear,
  shoes, and accessories, in a bunch of styles (vintage, y2k, grunge, cottagecore,
  streetwear). Each has `id`, `title`, `description`, `category`, `style_tags`, `size`,
  `condition`, `price`, `colors`, `brand`, `platform`. Load it with `load_listings()`.
- `data/wardrobe_schema.json` — the wardrobe format plus a 10-item `example_wardrobe`
  and an `empty_wardrobe`. Load with `get_example_wardrobe()` / `get_empty_wardrobe()`.

## Files

```
ai201-project2-fitfindr-starter/
├── agent.py                 # run_agent() planning loop + _parse_query()
├── app.py                   # Gradio UI + handle_query()
├── tools.py                 # the 3 tools
├── tests/test_tools.py      # tests, one per failure mode
├── data/                    # listings.json, wardrobe_schema.json
├── utils/data_loader.py     # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
└── planning.md              # the design doc I wrote before coding
```
