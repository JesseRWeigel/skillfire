"""Join the inventory to the events and answer the question the task actually asks.

Four numbers per skill, and the fourth is the only interesting one.

  fires            times the Skill tool ran with this skill's name.
  sessions_live    sessions that started after this skill was installed. Its standing context
                   cost was paid once in each of them.
  opportunities    live sessions holding at least one user turn where this skill's distinctive
                   trigger vocabulary appeared. A proxy for "the situation arose", explained in
                   triggers.py, and it is a proxy rather than a fact.
  displaced        opportunities where this skill did not fire. Split into `displaced_by_skill`,
                   where a DIFFERENT skill fired in that session, and `displaced_unassisted`,
                   where no skill fired at all and the work was done with ordinary tools.

WHAT THIS CANNOT SEE, stated up front because the honest version of this measurement is mostly
a list of what it cannot see.

  * The consideration set. A transcript records the tool calls that happened. It has no field
    for "the model read the skill list and decided none applied", so the difference between
    "considered and rejected" and "never noticed" is not recoverable from this data at all.
  * Relevance. Trigger vocabulary is lexical. A session about the word "deploy" is not
    necessarily a session where a deployment skill would have helped.
  * Availability changes. Install time comes from `installed_plugins.json`, which records the
    first install and the last update. A plugin that was enabled, disabled and enabled again
    leaves no trace, so `sessions_live` is an upper bound on exposure.
  * Whether firing was correct. A skill that fires on the wrong thing counts as a fire here.

RARE IS NOT DEAD. The distinction the task asks for lives in `opportunities`. A skill with zero
fires and zero opportunities was never in a position to fire, which is a statement about the
work rather than about the skill. A skill with zero fires and many opportunities is the dead
weight candidate. Those two are separate rows in every output and are never summed together.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillRow:
    name: str
    origin: str
    source: str
    est_tokens: int
    available_from: float
    fires: int = 0
    fire_sessions: int = 0
    manifest_reads: int = 0
    sessions_live: int = 0
    opportunities: int = 0
    opportunity_turns: int = 0
    fires_in_opportunity: int = 0
    displaced_by_skill: int = 0
    displaced_unassisted: int = 0
    trigger_terms: int = 0

    @property
    def displaced(self) -> int:
        return self.displaced_by_skill + self.displaced_unassisted

    @property
    def capture_rate(self):
        """Share of opportunities where the skill fired. None when there were none.

        The numerator is opportunity sessions that fired, not all sessions that fired. A skill
        can fire in a session whose wording never matched its trigger vocabulary, and counting
        those on top produced a rate above 100 percent on the first run.
        """
        if not self.opportunities:
            return None
        return self.fires_in_opportunity / self.opportunities

    @property
    def tokens_spent(self) -> int:
        """Standing cost paid across every session that carried this skill."""
        return self.est_tokens * self.sessions_live

    @property
    def verdict_class(self) -> str:
        if self.fires:
            return "fired"
        if self.opportunities:
            return "never-fired-had-openings"
        return "never-fired-no-opening"


@dataclass
class Corpus:
    sessions: int = 0
    sessions_with_time: int = 0
    records: int = 0
    bad_json: int = 0
    user_turns: int = 0
    sidechain_user_turns: int = 0
    truncated_turns: int = 0
    tool_calls: int = 0
    sessions_with_a_fire: int = 0
    fires_total: int = 0
    fires_unknown_skill: int = 0
    unknown_fired_names: list = field(default_factory=list)
    first_ts: float = 0.0
    last_ts: float = 0.0


def analyse(skills, facts_list, terms_by_skill) -> tuple[dict, Corpus]:
    rows = {
        s.name: SkillRow(name=s.name, origin=s.origin, source=s.source,
                         est_tokens=s.est_tokens, available_from=s.available_from,
                         trigger_terms=len(terms_by_skill.get(s.name, ())))
        for s in skills
    }
    known = set(rows)
    corpus = Corpus()
    unknown: dict[str, int] = {}

    for facts in facts_list:
        corpus.sessions += 1
        corpus.records += facts.records
        corpus.bad_json += facts.bad_json
        corpus.user_turns += facts.user_turns
        corpus.sidechain_user_turns += facts.sidechain_user_turns
        corpus.truncated_turns += facts.truncated_turns
        corpus.tool_calls += facts.tool_calls
        if facts.first_ts:
            corpus.sessions_with_time += 1
            corpus.first_ts = (facts.first_ts if not corpus.first_ts
                               else min(corpus.first_ts, facts.first_ts))
            corpus.last_ts = max(corpus.last_ts, facts.last_ts)

        fired_here = set()
        for _, name, _ in facts.fires:
            corpus.fires_total += 1
            if name in known:
                rows[name].fires += 1
                fired_here.add(name)
            else:
                corpus.fires_unknown_skill += 1
                unknown[name] = unknown.get(name, 0) + 1
        if facts.fires:
            corpus.sessions_with_a_fire += 1
        for name in fired_here:
            rows[name].fire_sessions += 1
        for name in facts.manifest_reads:
            for candidate in rows:
                if candidate == name or candidate.endswith(":" + name):
                    rows[candidate].manifest_reads += 1

        for name, row in rows.items():
            live = (not row.available_from) or (not facts.first_ts) or \
                facts.first_ts >= row.available_from
            if not live:
                continue
            row.sessions_live += 1
            turns = facts.matched.get(name, 0)
            if not turns:
                continue
            row.opportunities += 1
            row.opportunity_turns += turns
            if name in fired_here:
                row.fires_in_opportunity += 1
                continue
            if fired_here:
                row.displaced_by_skill += 1
            else:
                row.displaced_unassisted += 1

    corpus.unknown_fired_names = sorted(unknown)
    return rows, corpus


def totals(rows, corpus) -> dict:
    values = list(rows.values())
    fired = [r for r in values if r.verdict_class == "fired"]
    openings = [r for r in values if r.verdict_class == "never-fired-had-openings"]
    silent = [r for r in values if r.verdict_class == "never-fired-no-opening"]
    spent = sum(r.tokens_spent for r in values)
    fires = sum(r.fires for r in values)
    return {
        "skills": len(values),
        "fired": len(fired),
        "never_fired_had_openings": len(openings),
        "never_fired_no_opening": len(silent),
        "fires_matched_to_inventory": fires,
        "standing_tokens_per_session": sum(r.est_tokens for r in values),
        "standing_tokens_spent_estimate": spent,
        "tokens_per_fire": (spent // fires) if fires else None,
        "opportunities_total": sum(r.opportunities for r in values),
        "displaced_total": sum(r.displaced for r in values),
        "displaced_unassisted": sum(r.displaced_unassisted for r in values),
        "displaced_by_skill": sum(r.displaced_by_skill for r in values),
        "sessions": corpus.sessions,
        "sessions_with_a_fire": corpus.sessions_with_a_fire,
    }
