"""Precompute public guru results. Usage: python precompute_gurus.py

Run locally by a human (needs ANTHROPIC_API_KEY). Uses the existing news cache
only and is never run in CI.
"""

import json
import os
import sys

if os.environ.get("CI"):
    sys.exit("precompute_gurus.py must be run locally, never in CI")

import engine
import insights

GURUS = [
    {"id": "dip", "name": "Sample trader: Dip Buyer", "style": "dip", "bio": "Buys quality names after several consecutive down days and sells into the rebound."},
    {"id": "breakout", "name": "Sample trader: Breakout", "style": "breakout", "bio": "Buys stocks breaking out above their 20-day average on strong momentum and sells when momentum fades."},
    {"id": "defensive", "name": "Sample trader: Defensive", "style": "defensive", "bio": "Trims positions when the broad market weakens and only adds exposure on calm, rising days."},
]
GURUS_DIR = "data/gurus"


def precompute_guru(guru: dict) -> dict:
    result = engine.run_discovery(f"data/guru_{guru['id']}.csv", lambda update: None)
    result["insights"] = insights.build_insights(result)

    public = {"guru_id": guru["id"], **{k: result[k] for k in ("status", "round", "hypotheses", "baseline", "exceptions", "summary", "insights")}}

    os.makedirs(GURUS_DIR, exist_ok=True)
    with open(os.path.join(GURUS_DIR, f"{guru['id']}.json"), "w") as f:
        json.dump(public, f, indent=2)
    with open(os.path.join(GURUS_DIR, f"{guru['id']}.rules.json"), "w") as f:
        json.dump(result["rule_codes"], f, indent=2)

    return public


def main() -> None:
    # Force news.get_headlines to use the existing cache only (no Bright Data calls)
    os.environ.pop("BRIGHTDATA_API_KEY", None)
    os.environ.pop("BRIGHTDATA_ZONE", None)

    os.makedirs(GURUS_DIR, exist_ok=True)
    for guru in GURUS:
        public = precompute_guru(guru)
        kept = [h for h in public["hypotheses"] if h.get("status") == "kept"]
        matches = [h["holdout_match"] for h in kept if h.get("holdout_match") is not None]
        best = f"{max(matches):.2f}" if matches else "n/a"
        print(f"{guru['id']}: kept {len(kept)}/{len(public['hypotheses'])} hypotheses, "
              f"{len(public['exceptions'])} exceptions, {len(public['insights'])} insights, best holdout_match {best}")

    with open(os.path.join(GURUS_DIR, "index.json"), "w") as f:
        json.dump(GURUS, f, indent=2)


if __name__ == "__main__":
    main()
