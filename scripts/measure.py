#!/usr/bin/env python3
"""Deterministic fingerprint of what skillfire measures. Measurements, never verdicts.

Everything runs against the synthetic machine in `skillfire/fixtures.py`, so the answer is the
same on any box and the sabotage suite has something stable to move.

Two rules the fingerprint has to obey, both learned the hard way elsewhere in this fleet.

  * No absolute path appears anywhere in it. The sabotage null control copies the tree into a
    differently named directory and requires an identical fingerprint. A fingerprint that
    tracks the working directory makes gate two free for every sabotage below it.
  * It is wide. Every field the analysis produces is in here, including the ones that are zero,
    because a fingerprint that cannot see the thing being attacked turns a real sabotage into a
    no-op and tempts you to delete the sabotage rather than widen the fingerprint.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from skillfire import fixtures, inventory, pipeline, redact, report, triggers  # noqa: E402


def main() -> int:
    workspace = tempfile.mkdtemp(prefix="skillfire-measure-")
    try:
        home, transcripts = fixtures.materialise(workspace)
        skills, stats = inventory.build(home=home)
        candidate = triggers.build(skills)
        rows, corpus, summary = pipeline.run(claude_home=home, transcripts=transcripts)

        lines = ["=== inventory"]
        for skill in skills:
            lines.append(f"  {skill.name} origin={skill.origin} chars={skill.desc_chars} "
                         f"tok={skill.est_tokens} terms={len(candidate[skill.name])} "
                         f"since={int(skill.available_from)}")
        lines.append(f"  enabled_plugins={stats.enabled_plugins} "
                     f"disabled_on_disk={stats.disabled_on_disk} "
                     f"dirs={stats.skill_dirs_seen} malformed={stats.malformed} "
                     f"no_description={stats.no_description}")

        lines.append("=== trigger terms")
        for name in sorted(candidate):
            lines.append(f"  {name} -> {'|'.join(sorted(candidate[name]))}")

        lines.append("=== corpus")
        for field in ("sessions", "sessions_with_time", "records", "bad_json", "user_turns",
                      "sidechain_user_turns", "truncated_turns", "tool_calls",
                      "sessions_with_a_fire", "fires_total", "fires_unknown_skill"):
            lines.append(f"  {field}={getattr(corpus, field)}")
        lines.append(f"  unknown_fired_names={corpus.unknown_fired_names}")
        lines.append(f"  span_seconds={int(corpus.last_ts - corpus.first_ts)}")

        lines.append("=== rows")
        for row in sorted(rows.values(), key=lambda r: r.name):
            rate = "none" if row.capture_rate is None else f"{row.capture_rate:.4f}"
            lines.append(
                f"  {row.name} origin={row.origin} tok={row.est_tokens} fires={row.fires} "
                f"fire_sessions={row.fire_sessions} live={row.sessions_live} "
                f"opp={row.opportunities} opp_turns={row.opportunity_turns} "
                f"in_opp={row.fires_in_opportunity} disp_skill={row.displaced_by_skill} "
                f"disp_none={row.displaced_unassisted} reads={row.manifest_reads} "
                f"spent={row.tokens_spent} capture={rate} class={row.verdict_class}")

        lines.append("=== summary")
        for key in sorted(summary):
            if key == "inventory":
                continue
            value = summary[key]
            if isinstance(value, float):
                value = f"{value:.6f}"
            lines.append(f"  {key}={value}")
        for key in sorted(summary["inventory"]):
            lines.append(f"  inventory.{key}={summary['inventory'][key]}")

        lines.append("=== rendering")
        text = report.render_text(rows, corpus, summary)
        blob = report.render_json(rows, corpus, summary)
        lines.append(f"  text_lines={len(text.splitlines())} "
                     f"sha={hashlib.sha256(text.encode()).hexdigest()[:16]}")
        lines.append(f"  json_chars={len(blob)} "
                     f"sha={hashlib.sha256(blob.encode()).hexdigest()[:16]}")

        lines.append("=== leaks")
        planted = fixtures.planted_values()
        leaked = sorted(label for label, value in planted.items()
                        if value in text or value in blob)
        lines.append(f"  planted={len(planted)} leaked={len(leaked)} labels={leaked}")
        home_path = os.path.expanduser("~")
        lines.append(f"  running_home_in_output="
                     f"{int(home_path in text or home_path in blob)}")
        lines.append(f"  user_skill_name_in_output="
                     f"{int('my-private-workflow' in text or 'my-private-workflow' in blob)}")

        # The body is scrubbed before it is printed or hashed. One fixture session fires a skill
        # whose NAME is shaped like a credential, which is a legal skill name and therefore
        # passes the structural rule, so an unscrubbed fingerprint would carry a token into
        # anything the transcript gets pasted into.
        body = redact.scrub("\n".join(lines))
        print(body)
        print(f"\nFINGERPRINT {hashlib.sha256(body.encode()).hexdigest()}")
        print(f"LINES {len(lines)}")
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
