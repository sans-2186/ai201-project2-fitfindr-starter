"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a search description, optional size, and optional max_price from a
    natural-language query. Uses regex/string handling — deterministic and free,
    so we don't spend an LLM call on parsing.

    Examples:
        "vintage graphic tee under $30"   → desc="vintage graphic tee", max_price=30.0
        "90s track jacket in size M"      → desc="90s track jacket", size="M"
        "black combat boots size 8"       → desc="black combat boots", size="8"
    """
    text = query.strip()

    # --- max_price: "under $30", "below 40", "less than $25", "$30" -----------
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max|<)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I
    )
    if not price_match:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if price_match:
        max_price = float(price_match.group(1))

    # --- size: "size M", "size 8", "in size XL" -------------------------------
    size = None
    size_match = re.search(r"\bsize\s+([a-z0-9.]+)", text, re.I)
    if size_match:
        size = size_match.group(1).upper()

    # --- description: strip out the size/price phrases we just consumed -------
    desc = text
    desc = re.sub(
        r"(?:under|below|less than|max|<)\s*\$?\s*\d+(?:\.\d+)?", " ", desc, flags=re.I
    )
    desc = re.sub(r"\$\s*\d+(?:\.\d+)?", " ", desc)
    desc = re.sub(r"\bin\s+size\s+[a-z0-9.]+", " ", desc, flags=re.I)
    desc = re.sub(r"\bsize\s+[a-z0-9.]+", " ", desc, flags=re.I)
    # Drop dangling connector words left behind by the removals.
    desc = re.sub(r"\b(in|for|under|a|an)\b\s*$", " ", desc.strip(), flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip()

    return {"description": desc, "size": size, "max_price": max_price}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search. Branch on the result — this is what makes the loop a
    # planning loop rather than a fixed pipeline.
    session["search_results"] = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    if not session["search_results"]:
        # No matches → set a helpful error and STOP. Do not call the LLM tools.
        bits = []
        if parsed["max_price"] is not None:
            bits.append(f"raising your budget above ${parsed['max_price']:.0f}")
        if parsed["size"]:
            bits.append("dropping the size filter")
        bits.append("loosening your search terms")
        suggestions = ", ".join(bits)
        session["error"] = (
            f"No listings matched \"{parsed['description'] or query}\". "
            f"Try {suggestions}."
        )
        return session

    # Step 4: select the top (most relevant) result.
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest an outfit from the selected item + wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=session["wardrobe"],
    )

    # Step 6: create a fit card — guarded so we don't caption an empty suggestion.
    if session["selected_item"] and (session["outfit_suggestion"] or "").strip():
        session["fit_card"] = create_fit_card(
            outfit=session["outfit_suggestion"],
            new_item=session["selected_item"],
        )

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
