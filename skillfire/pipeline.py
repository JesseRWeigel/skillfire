"""Wire inventory, triggers, events and analysis into one call."""

from __future__ import annotations

import re
from pathlib import Path

from . import analyze, events, inventory, triggers


def slash_map(skills) -> dict:
    """Slash names that map onto a skill.

    Claude Code exposes some skills as `/name`, and a plugin skill can be typed either as
    `plugin:skill` or, when unambiguous, as `skill`. An ambiguous bare name maps to nothing
    rather than to a guess.
    """
    out: dict[str, str] = {}
    clash: set[str] = set()
    for skill in skills:
        out[skill.name] = skill.name
        bare = skill.name.split(":")[-1]
        if bare == skill.name:
            continue
        if bare in out and out[bare] != skill.name:
            clash.add(bare)
        else:
            out[bare] = skill.name
    for name in clash:
        out.pop(name, None)
    return out


def run(claude_home=None, transcripts=None, project_dirs=(), limit: int = 0):
    home = Path(claude_home) if claude_home else inventory.claude_home()
    skills, inv_stats = inventory.build(home=home, project_dirs=project_dirs)
    candidate_terms = triggers.build(skills)
    vocab = triggers.Vocabulary(candidate_terms)
    slashes = slash_map(skills)

    paths = events.find(transcripts)
    if limit:
        paths = paths[:limit]
    facts = [events.scan_file(path, vocab, slashes) for path in paths]

    total_turns = sum(f.user_turns for f in facts)
    kept_terms, dropped = triggers.prune(vocab, events.turn_frequency(facts), total_turns)
    matcher = triggers.Matcher(kept_terms)
    events.resolve(facts, matcher)

    rows, corpus = analyze.analyse(skills, facts, kept_terms)
    summary = analyze.totals(rows, corpus)
    # A measurement of a privacy property rather than a claim about one. A transcript path
    # names a home directory and a project, so if any session identifier stops being an opaque
    # digest this drops to zero and the fingerprint moves.
    summary["session_ids_opaque"] = int(
        all(re.fullmatch(r"[0-9a-f]{12}", f.session) for f in facts))
    # The other half of the same property. Every word a scan retained has to have come from the
    # closed vocabulary, otherwise arbitrary transcript words are sitting in memory in a field
    # that could be serialised by any later change. Zero is the only acceptable value and it is
    # measured rather than asserted, so a regression moves the fingerprint.
    summary["turn_terms_outside_vocabulary"] = sum(
        len(set(terms) - vocab.terms) for f in facts for terms in f.turn_terms)
    summary["trigger_terms_candidate"] = len(vocab.terms)
    summary["trigger_terms_dropped_as_filler"] = len(dropped)
    summary["trigger_terms_total"] = matcher.n_terms
    summary["inventory"] = {
        "enabled_plugins": inv_stats.enabled_plugins,
        "disabled_on_disk": inv_stats.disabled_on_disk,
        "skill_dirs_seen": inv_stats.skill_dirs_seen,
        "malformed": inv_stats.malformed,
        "no_description": inv_stats.no_description,
        "plugins_without_path": inv_stats.plugins_without_path,
    }
    return rows, corpus, summary
