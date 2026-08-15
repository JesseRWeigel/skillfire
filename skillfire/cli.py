"""Command line entry point.

    python3 -m skillfire report            measure this machine
    python3 -m skillfire report --json     the same thing as JSON
    python3 -m skillfire inventory         what is loaded and what it costs

Reading is read only. Nothing here opens a transcript for writing, and the only paths it takes
are the ones it was told about.
"""

from __future__ import annotations

import argparse
import sys

from . import inventory, pipeline, report, triggers


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="skillfire", description=__doc__)
    parser.add_argument("mode", choices=["report", "inventory"])
    parser.add_argument("--claude-home", default=None,
                        help="defaults to ~/.claude or $SKILLFIRE_CLAUDE_HOME")
    parser.add_argument("--transcripts", default=None,
                        help="defaults to ~/.claude/projects or $CLAUDE_PROJECTS_DIR")
    parser.add_argument("--limit", type=int, default=0, help="scan at most N transcripts")
    parser.add_argument("--top", type=int, default=0, help="print only the first N rows")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "inventory":
        skills, stats = inventory.build(
            home=args.claude_home and __import__("pathlib").Path(args.claude_home))
        terms = triggers.build(skills)
        cost = inventory.standing_cost(skills)
        print(f"{cost['skills']} skills, {cost['description_chars']} description characters, "
              f"about {cost['est_tokens']} tokens in every session")
        print(f"{stats.enabled_plugins} enabled plugins, {stats.disabled_on_disk} installed but "
              f"switched off, {stats.no_description} skills with no description")
        for skill in skills:
            print(f"  {skill.name:48} {skill.est_tokens:5} tok  "
                  f"{len(terms.get(skill.name, ())):3} trigger terms")
        return 0

    rows, corpus, summary = pipeline.run(
        claude_home=args.claude_home, transcripts=args.transcripts, limit=args.limit)
    if not corpus.sessions:
        print("no transcripts found. Point --transcripts at a directory of .jsonl sessions.",
              file=sys.stderr)
        return 2
    if args.json:
        print(report.render_json(rows, corpus, summary))
    else:
        print(report.render_text(rows, corpus, summary, limit=args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
