#!/usr/bin/env python3
"""
Comprehensive acceptance test suite for the voice pipeline.
Tests routing, splitting, backlinks, cross-linking, Dataview blocks, and edge cases.
Uses the real Claude API — requires ANTHROPIC_API_KEY in environment.

Usage:
  cd /home/jschools/voice-pipeline
  source .env && export ANTHROPIC_API_KEY
  .venv/bin/python tests/test_pipeline.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
import config
import prompts
from pipeline import add_cross_links

DATE = "2026-05-19"
PASS_COUNT = 0
FAIL_COUNT = 0


# ── helpers ──────────────────────────────────────────────────────────────────

def call_claude(transcript: str,
                existing_notes: list[str] | None = None,
                personal_daily: str | None = None,
                work_daily: str | None = None) -> list[dict]:
    client = anthropic.Anthropic()
    raw = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_TOKENS,
        system=prompts.SYSTEM,
        messages=[{"role": "user", "content": prompts.user_prompt(
            transcript, DATE, personal_daily, work_daily, existing_notes
        )}],
    ).content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    return result if isinstance(result, list) else [result]


def check(label: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    \033[32m✓\033[0m {label}")
    else:
        FAIL_COUNT += 1
        print(f"    \033[31m✗\033[0m {label}{f'  →  {detail}' if detail else ''}")


def section(title: str):
    print(f"\n  \033[1m{title}\033[0m")
    print(f"  {'─' * 56}")


def all_content(notes: list[dict]) -> str:
    return " ".join(n["content"] for n in notes)


# ── unit tests (no API) ───────────────────────────────────────────────────────

section("Unit: add_cross_links")

single = [{"vault": "work", "filename": "2026-05-19-note.md", "title": "Only Note",
           "content": "## Summary\nSome content.", "type": "topic", "folder": "Notes", "tags": []}]
result = add_cross_links(single)
check("single note — no change", result[0]["content"] == single[0]["content"])

two = [
    {"vault": "work",     "filename": "2026-05-19-work.md",     "title": "Work Note",
     "content": "## Summary\nWork stuff.\n\n## Related\n- [[link to related note if one exists, otherwise omit]]",
     "type": "topic", "folder": "Notes", "tags": []},
    {"vault": "personal", "filename": "2026-05-19-personal.md", "title": "Personal Note",
     "content": "## Summary\nPersonal stuff.", "type": "topic", "folder": "Notes/Personal", "tags": []},
]
linked = add_cross_links(two)
check("work note links to personal",  "[[2026-05-19-personal|Personal Note]]" in linked[0]["content"],
      linked[0]["content"][-200:])
check("personal note links to work",  "[[2026-05-19-work|Work Note]]"         in linked[1]["content"],
      linked[1]["content"][-200:])
check("placeholder stripped",         "omit]]" not in linked[0]["content"])
check("Related section created in personal note", "## Related" in linked[1]["content"])

three = [
    {"vault": "work",     "filename": "a.md", "title": "A", "content": "stuff", "type": "topic", "folder": "Notes", "tags": []},
    {"vault": "personal", "filename": "b.md", "title": "B", "content": "stuff", "type": "topic", "folder": "Notes/Personal", "tags": []},
    {"vault": "personal", "filename": "c.md", "title": "C", "content": "stuff", "type": "topic", "folder": "Notes/Investing", "tags": []},
]
linked3 = add_cross_links(three)
check("A links to both B and C", "[[b|B]]" in linked3[0]["content"] and "[[c|C]]" in linked3[0]["content"])
check("B links to A and C",      "[[a|A]]" in linked3[1]["content"] and "[[c|C]]" in linked3[1]["content"])
check("C links to A and B",      "[[a|A]]" in linked3[2]["content"] and "[[b|B]]" in linked3[2]["content"])


# ── API tests ─────────────────────────────────────────────────────────────────

section("Routing: pure work → work vault")
notes = call_claude("Had standup with the FSM team. Need to open a ServiceNow change request for the server migration — CMDB records are stale.")
check("returns list",        isinstance(notes, list))
check("single note",         len(notes) == 1,           f"got {len(notes)}")
check("vault = work",        notes[0]["vault"] == "work", f"got {notes[0]['vault']}")
check("has required keys",   all(k in notes[0] for k in ("vault","type","folder","filename","title","tags","content")))


section("Routing: pure personal → personal vault")
notes = call_claude("Been thinking about rebalancing my portfolio. Moving out of QQQ into SCHD and some REITs for dividend income.")
check("returns list",           isinstance(notes, list))
check("single note",            len(notes) == 1,               f"got {len(notes)}")
check("vault = personal",       notes[0]["vault"] == "personal", f"got {notes[0]['vault']}")
check("investing folder",       "Investing" in notes[0]["folder"], f"got {notes[0]['folder']}")


section("Routing: ambiguous content defaults to personal")
notes = call_claude("Want to get better at Python and data analysis. Thinking about taking an online course.")
check("vault = personal", notes[0]["vault"] == "personal", f"got {notes[0]['vault']}")


section("Splitting: mixed recording → multiple vaults")
notes = call_claude(
    "Work: opened CHG0042891 to patch the broken assignment group lookup in ServiceNow — affects pre-Q1 catalog items. "
    "Personal: barbecue this weekend, Sean's bringing pie, Shannon's doing watermelon, I'm on burgers and dogs. "
    "Also, Biscuit the golden retriever in sunglasses is the best thing I've seen all week."
)
vaults = [n["vault"] for n in notes]
check("returns 2+ notes",    len(notes) >= 2,    f"got {len(notes)}")
check("has work note",       "work" in vaults)
check("has personal note",   "personal" in vaults)
work_n = next(n for n in notes if n["vault"] == "work")
pers_n = next(n for n in notes if n["vault"] == "personal")
check("work content in work note",       "CHG" in work_n["content"] or "ServiceNow" in work_n["content"] or "assignment" in work_n["content"].lower())
check("personal content not in work",    "barbecue" not in work_n["content"].lower() and "biscuit" not in work_n["content"].lower())
linked_notes = add_cross_links(notes)
check("cross-links injected",            "[[" in all_content(linked_notes))
for n in notes:
    print(f"      [{n['vault'].upper()}] {n['folder']}/{n['filename']}")


section("Note types: daily reflection → type=daily")
notes = call_claude("End of day. Most important thing was shipping the knowledge article. Grateful for the team. Worth noting: scope creep on the AI project was real but we got there.")
check("has daily type", any(n["type"] in ("daily", "daily_append") for n in notes), str([n["type"] for n in notes]))
daily = next((n for n in notes if n["type"] in ("daily", "daily_append")), None)
if daily:
    check("daily folder", "Daily" in daily["folder"], f"got {daily['folder']}")


section("Note types: focused topic → type=topic")
notes = call_claude("Reading Die With Zero by Bill Perkins. The core argument: optimize for memory dividends, not estate size. Convert wealth into experiences while healthy enough to enjoy them.")
check("topic type",       notes[0]["type"] == "topic",    f"got {notes[0]['type']}")
check("learning folder",  "Learning" in notes[0]["folder"], f"got {notes[0]['folder']}")
check("personal vault",   notes[0]["vault"] == "personal",  f"got {notes[0]['vault']}")


section("Note types: meeting → meetings folder")
notes = call_claude("Had a meeting with Sophie about the AI data support project. Three stories left, knowledge article in draft, she wants it done by end of sprint Friday.")
check("work vault",      notes[0]["vault"] == "work",  f"got {notes[0]['vault']}")
meeting_note = next((n for n in notes if "Meeting" in n["folder"]), None)
check("routed to Meetings folder", meeting_note is not None, f"folders: {[n['folder'] for n in notes]}")


section("Backlinks: uses existing note titles")
existing = ["NowAssist", "FSD Dashboards", "Restarting a failed workflow"]
notes = call_claude(
    "Deep dive on the NowAssist project: it uses AI to surface relevant knowledge articles and related incidents "
    "to agents during live contacts. The FSD Dashboards feed into this by showing open items per team. "
    "Key finding: system prompts need heavy configuration to get quality suggestions.",
    existing_notes=existing
)
content = all_content(notes)
check("wikilinks present",        "[[" in content,            "no [[wikilinks]] found")
check("NowAssist or FSD linked",  "[[NowAssist]]" in content or "[[FSD Dashboards]]" in content,
      f"content snippet: {content[:400]}")


section("Dataview: daily note contains dataview block")
notes = call_claude("Morning reflection. Busy day ahead — ServiceNow dashboards and a run after work. Grateful for coffee.")
daily_notes = [n for n in notes if n["type"] in ("daily", "daily_append")]
check("has daily note",              len(daily_notes) >= 1)
if daily_notes:
    dv_present = any("dataview" in n["content"].lower() for n in daily_notes)
    check("dataview block present",  dv_present, "no dataview block found in daily note content")


section("daily_append: appends to existing daily note")
existing_personal = """---
title: Daily — 2026-05-19
date: 2026-05-19
type: daily
---

# Daily — 2026-05-19

## Most Important Thing
Ship the knowledge article.
"""
notes = call_claude(
    "Quick personal addendum — just remembered I need to call mom this weekend.",
    personal_daily=existing_personal
)
check("returns list",         isinstance(notes, list))
append_note = next((n for n in notes if n["type"] == "daily_append"), None)
check("daily_append type",    append_note is not None, f"types: {[n['type'] for n in notes]}")
if append_note:
    check("personal vault",   append_note["vault"] == "personal", f"got {append_note['vault']}")


section("Robustness: markdown fence stripping")
import anthropic as _anthropic
client = _anthropic.Anthropic()
raw_with_fence = client.messages.create(
    model=config.CLAUDE_MODEL,
    max_tokens=512,
    system="Respond with a JSON array wrapped in ```json fences.",
    messages=[{"role": "user", "content": "Return [{\"test\": true}]"}],
).content[0].text.strip()
if raw_with_fence.startswith("```"):
    stripped = raw_with_fence.split("\n", 1)[1].rsplit("```", 1)[0].strip()
else:
    stripped = raw_with_fence
try:
    parsed = json.loads(stripped)
    check("fence stripping works", isinstance(parsed, list))
except Exception as e:
    check("fence stripping works", False, str(e))


section("Robustness: single note still returned as list")
notes = call_claude("Reminder: buy milk on the way home.")
check("returns list",       isinstance(notes, list))
check("has at least 1 note", len(notes) >= 1)
check("has all required keys", all(k in notes[0] for k in ("vault","type","folder","filename","title","tags","content")))


# ── summary ───────────────────────────────────────────────────────────────────

total = PASS_COUNT + FAIL_COUNT
print(f"\n  {'═' * 58}")
color = "\033[32m" if FAIL_COUNT == 0 else "\033[31m"
print(f"  {color}{PASS_COUNT}/{total} passed{'\033[0m'}{'   (' + str(FAIL_COUNT) + ' failed)' if FAIL_COUNT else ''}")
print(f"  {'═' * 58}\n")
sys.exit(0 if FAIL_COUNT == 0 else 1)
