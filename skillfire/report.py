"""Render the analysis. Counts, names from a closed vocabulary, and timestamps. Nothing else.

Every string that leaves here goes through `redact.scrub` on the way out, which is dormant while
the structural rule in events.py holds.
"""

from __future__ import annotations

import json

from . import redact


def _rate(value):
    return "-" if value is None else f"{value * 100:.0f}%"


def rows_as_dicts(rows) -> list:
    out = []
    for row in sorted(rows.values(), key=lambda r: (-r.fires, -r.opportunities, r.name)):
        out.append({
            "skill": redact.public_name(row.name, row.origin),
            "origin": row.origin,
            "est_tokens": row.est_tokens,
            "trigger_terms": row.trigger_terms,
            "fires": row.fires,
            "fire_sessions": row.fire_sessions,
            "manifest_reads": row.manifest_reads,
            "sessions_live": row.sessions_live,
            "opportunities": row.opportunities,
            "opportunity_turns": row.opportunity_turns,
            "fires_in_opportunity": row.fires_in_opportunity,
            "displaced_by_skill": row.displaced_by_skill,
            "displaced_unassisted": row.displaced_unassisted,
            "capture_rate": row.capture_rate,
            "tokens_spent": row.tokens_spent,
            "class": row.verdict_class,
        })
    return out


def render_json(rows, corpus, summary) -> str:
    payload = {
        "summary": summary,
        "corpus": {
            "sessions": corpus.sessions,
            "sessions_with_time": corpus.sessions_with_time,
            "records": corpus.records,
            "bad_json": corpus.bad_json,
            "user_turns": corpus.user_turns,
            "sidechain_user_turns": corpus.sidechain_user_turns,
            "truncated_turns": corpus.truncated_turns,
            "tool_calls": corpus.tool_calls,
            "sessions_with_a_fire": corpus.sessions_with_a_fire,
            "fires_total": corpus.fires_total,
            "fires_unknown_skill": corpus.fires_unknown_skill,
            "unknown_fired_names": [redact.public_name(n, "builtin")
                                    for n in corpus.unknown_fired_names],
        },
        "skills": rows_as_dicts(rows),
    }
    return redact.scrub(json.dumps(payload, indent=2, sort_keys=True))


def render_text(rows, corpus, summary, limit: int = 0) -> str:
    lines = []
    lines.append(f"{summary['skills']} skills loaded in every session, "
                 f"about {summary['standing_tokens_per_session']} tokens of description")
    lines.append(f"{corpus.sessions} transcripts, {corpus.user_turns} user turns, "
                 f"{corpus.tool_calls} tool calls")
    lines.append(f"{summary['fires_matched_to_inventory']} fires matched to the inventory in "
                 f"{corpus.sessions_with_a_fire} session(s); "
                 f"{corpus.fires_unknown_skill} fire(s) named something not installed")
    per_fire = summary["tokens_per_fire"]
    lines.append(f"estimated standing spend {summary['standing_tokens_spent_estimate']} tokens, "
                 + (f"{per_fire} tokens per fire" if per_fire else "no fires to divide by"))
    lines.append("")
    lines.append(f"  fired                        {summary['fired']}")
    lines.append(f"  never fired, had openings    {summary['never_fired_had_openings']}")
    lines.append(f"  never fired, no opening      {summary['never_fired_no_opening']}")
    lines.append("")
    header = (f"{'skill':44} {'tok':>5} {'fire':>5} {'opp':>5} {'disp':>5} "
              f"{'cap':>5}  class")
    lines.append(header)
    lines.append("-" * len(header))
    data = rows_as_dicts(rows)
    if limit:
        data = data[:limit]
    for row in data:
        lines.append(f"{row['skill'][:44]:44} {row['est_tokens']:5} {row['fires']:5} "
                     f"{row['opportunities']:5} "
                     f"{row['displaced_by_skill'] + row['displaced_unassisted']:5} "
                     f"{_rate(row['capture_rate']):>5}  {row['class']}")
    return redact.scrub("\n".join(lines))
