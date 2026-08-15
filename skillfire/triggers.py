"""Turn each skill's description into the vocabulary that would have to appear for it to be relevant.

This is the honest half of the counterfactual and it deserves a paragraph rather than a comment.

A transcript records what fired. It does not record what was considered and passed over, so the
question "was this skill available and relevant and something else was used instead" cannot be
read off directly. What can be measured is a proxy: the frontmatter `description` is the only
text about a skill that is in front of the model when it decides, so if none of that description's
distinctive words ever appear in anything the human asked for, the skill's situation plausibly
never came up. If they appear often and the skill never fires, the situation plausibly came up
and was handled another way.

Two failure modes are designed against.

  * Generic words. Two filters, because a hand written stoplist is never finished. First, any
    term occurring in more than MAX_SKILLS_PER_TERM skill descriptions is dropped as
    undiscriminating. Second, and this is the one that matters, a term appearing in more than
    MAX_TURN_RATIO of the corpus's own user turns is dropped by `prune`. The first pass measured
    "already" and "their" as trigger terms, which put 59 skills in play across seven turns of
    chatter. Document frequency measured on the actual corpus removes that class of word without
    anybody having to think of it in advance.
  * Single accidental hits. One shared word is not evidence, so a turn counts as an opportunity
    only when MIN_DISTINCT_HITS different surviving trigger terms of the same skill appear in it.

Every threshold is a constant here so it is visible and so a reader can disagree with it.
Bigrams are kept as well as single words, because "pull request" and "test driven" discriminate
where "pull" and "test" do not.
"""

from __future__ import annotations

import re
from collections import Counter

MAX_SKILLS_PER_TERM = 4
MIN_DISTINCT_HITS = 2
MAX_TERMS_PER_SKILL = 24
MIN_TERM_LEN = 4
# A term in more than this share of the corpus's user turns describes the corpus, not a skill.
MAX_TURN_RATIO = 0.10
# Below this many turns a share is not an estimate of anything. On a ten turn corpus a ten
# percent ceiling drops any term used twice, which silently deleted two thirds of the fixture's
# trigger vocabulary the first time this ran.
MIN_TURN_CEILING = 5

WORD = re.compile(r"[a-z][a-z0-9_.-]*")

STOP = {
    "this", "that", "with", "when", "from", "into", "your", "user", "used", "uses", "using",
    "asks", "ask", "want", "wants", "need", "needs", "should", "would", "could", "will",
    "also", "just", "like", "only", "over", "than", "them", "they", "then", "there", "these",
    "those", "what", "which", "while", "about", "after", "before", "between", "both", "each",
    "more", "most", "other", "some", "such", "have", "has", "had", "does", "doing", "done",
    "make", "makes", "made", "help", "helps", "work", "works", "working", "code", "codebase",
    "file", "files", "project", "projects", "skill", "skills", "tool", "tools", "command",
    "commands", "create", "creating", "add", "adding", "new", "any", "all", "not", "for",
    "and", "the", "are", "you", "its", "it's", "how", "why", "run", "runs", "running",
    "example", "examples", "including", "includes", "include", "provides", "provide",
    "guidance", "expert", "based", "specific", "general", "support", "supports", "set",
    "sets", "setting", "settings", "one", "two", "way", "ways", "even", "never", "always",
    "trigger", "triggers", "triggering", "mention", "mentions", "mentioned", "asked",
    "request", "requests", "requested", "instead", "rather", "without", "within",
}


def tokens(text: str) -> set[str]:
    """Lowercase unigrams and bigrams. The one place transcript prose is touched."""
    words = WORD.findall(text.lower())
    out = set()
    previous = None
    for word in words:
        word = word.strip("._-")
        if not word:
            previous = None
            continue
        out.add(word)
        if previous:
            out.add(previous + " " + word)
        previous = word
    return out


def _candidate_terms(description: str) -> set[str]:
    raw = tokens(description)
    out = set()
    for term in raw:
        parts = term.split(" ")
        if len(parts) == 1:
            if len(term) < MIN_TERM_LEN or term in STOP or term.isdigit():
                continue
            out.add(term)
        else:
            if any(p in STOP or len(p) < 3 for p in parts):
                continue
            out.add(term)
    return out


def build(skills) -> dict[str, list[str]]:
    """Map skill name to its distinctive trigger terms, discarding terms shared too widely."""
    candidates = {s.name: _candidate_terms(s.description) for s in skills}
    spread: Counter = Counter()
    for terms in candidates.values():
        for term in terms:
            spread[term] += 1

    out: dict[str, list[str]] = {}
    for name, terms in candidates.items():
        keep = [t for t in terms if spread[t] <= MAX_SKILLS_PER_TERM]
        # Rarest first, so a skill with many terms keeps the ones that discriminate best.
        keep.sort(key=lambda t: (spread[t], -len(t), t))
        out[name] = sorted(keep[:MAX_TERMS_PER_SKILL])
    return out


class Vocabulary:
    """The closed set of terms a transcript scan is allowed to notice.

    This is what keeps the scan honest about privacy. A scan reduces each user turn to the
    subset of THIS set that appeared in it, so the only words that survive contact with a
    transcript are words that were already written down in a public skill description.
    """

    def __init__(self, terms_by_skill: dict[str, list[str]]):
        self.terms_by_skill = terms_by_skill
        self.terms: set[str] = set()
        for terms in terms_by_skill.values():
            self.terms.update(terms)

    def present(self, token_set: set[str]) -> frozenset:
        return frozenset(self.terms & token_set)


def prune(vocab: Vocabulary, turn_frequency, total_turns: int,
          max_ratio: float = MAX_TURN_RATIO) -> tuple[dict, list]:
    """Drop terms the corpus itself shows to be filler. Returns (kept terms, dropped terms)."""
    ceiling = max(max_ratio * total_turns, MIN_TURN_CEILING) if total_turns else 0
    dropped = sorted(term for term in vocab.terms if turn_frequency.get(term, 0) > ceiling)
    banned = set(dropped)
    kept = {name: [t for t in terms if t not in banned]
            for name, terms in vocab.terms_by_skill.items()}
    return kept, dropped


class Matcher:
    """Term set for one user turn in, set of skill names whose situation plausibly arose out.

    Holds an inverted index so one turn costs one dict lookup per term rather than a scan over
    every skill.
    """

    def __init__(self, terms_by_skill: dict[str, list[str]],
                 min_hits: int = MIN_DISTINCT_HITS):
        self.min_hits = min_hits
        self.index: dict[str, list[str]] = {}
        self.n_terms = 0
        for name, terms in terms_by_skill.items():
            for term in terms:
                self.index.setdefault(term, []).append(name)
                self.n_terms += 1

    def match(self, term_set) -> set[str]:
        hits: Counter = Counter()
        for term in term_set:
            for name in self.index.get(term, ()):
                hits[name] += 1
        return {name for name, count in hits.items() if count >= self.min_hits}
