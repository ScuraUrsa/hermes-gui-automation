"""hermes-teach: record what a user does, turn it into a parameterized skill,
replay it with an LLM in the loop, measure it, and promote stable procedures
to plain scripts (Playwright, AutoIt, xdotool).

Pipeline::

    record (desktop / browser)  ->  events.jsonl
    normalize                   ->  steps
    generalize (heuristic/LLM)  ->  procedure.yaml (params, conditions, Bitwarden refs)
    run                         ->  metrics.sqlite (status, verdict, streak)
    promote / compile           ->  script (after N accepted runs in a row)
"""

__version__ = "0.1.0"
