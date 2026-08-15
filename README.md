# skillfire

Measure which installed Claude Code skills actually fire, which never do, and what each one
costs in always-loaded context.

Catalog task: `AGENT-008`. One of a public catalog of build ideas:
https://github.com/JesseRWeigel/722-things-to-build

## What this is

Every installed skill puts its name and its frontmatter description into the system prompt of
every session, whether or not it is ever used. That is a standing cost paid on every request.
`skillfire` reads the Claude Code transcripts on a machine, counts how often each installed
skill was actually invoked, and divides.

It also tries the harder question the task asks for, which is the counterfactual: how often was
a skill available and its situation present and something else was used instead. See the limits
section, because the honest answer is that this is only partly measurable.

Nothing from a transcript body reaches any output. One function opens transcripts, and what it
returns is an opaque session id, integer counts, skill names from the inventory, and per turn
sets of words drawn from a closed vocabulary built out of public plugin descriptions. There is
no field it could put a sentence in. `docs/measured.json` and this README hold counts and skill
names only.

## The finding, on this machine

1080 transcripts, 19 March to 15 August 2026, against 106 skills from 27 enabled plugins.

- The 106 descriptions are about **9,622 tokens loaded into every single session**.
- **18 sessions out of 1080 invoked any skill at all.** Ten of those invocations named an
  installed skill; fifteen named a built-in that ships with the CLI rather than a plugin
  (`dataviz`, `loop`, `schedule`, `artifact-design`, `claude-api`, and once, incorrectly,
  `Bash`).
- **98 of the 106 never fired once.**
- Standing spend across the corpus works out at roughly **10.4 million tokens, or about one
  million tokens per fire.**
- Nobody ever opened a `SKILL.md` by hand instead of invoking it. That path is measured and it
  is zero.

The eight that fired: `huggingface-skills:huggingface-best` and `superpowers:systematic-
debugging` twice each, then `frontend-design:frontend-design`,
`superpowers:dispatching-parallel-agents`, `superpowers:writing-plans`,
`superpowers:using-superpowers`, `superpowers:subagent-driven-development` and
`superpowers:test-driven-development` once each.

The two plugins that dominate the cost are the two nobody uses. `vercel` and
`huggingface-skills` contribute 55 of the 106 skills and about 5,900 of the 9,622 tokens, and
between them fired twice.

## What the counterfactual can and cannot see

"Never fired" is easy. "Was available and relevant and something else was used instead" is the
number that would prove dead weight, and a transcript has no field for what the model
considered and passed over. So it is estimated, and the estimate is checked.

The proxy: each skill's frontmatter description is the only text about it in front of the model
at decision time, so it is reduced to distinctive terms. Terms shared by more than four skills
are dropped as undiscriminating, and terms appearing in more than a tenth of the corpus's user
turns are dropped as filler measured on the corpus itself rather than on a hand written
stoplist. A user turn carrying two or more of a skill's surviving terms is an opening. An
opening where the skill did not fire is displaced, split by whether some other skill fired in
that session or nothing did.

**How good the proxy is, measured rather than asserted.** Of the ten sessions that really did
fire an installed skill, two were flagged as an opening for the skill that fired. That is 20
percent recall on the only cases where the answer is known. The opening counts are therefore a
weak signal and the report says so in its own output. They bound the question rather than
settle it.

Specifically not detectable from this data:

- The consideration set. Whether a skill was weighed and rejected, or never noticed, leaves no
  trace.
- Relevance. A session containing the word "deploy" is not necessarily a session a deployment
  skill would have helped.
- Availability history. Install time comes from `installed_plugins.json`, which records the
  first install and the last update. A plugin enabled, disabled and re-enabled leaves no trace,
  so exposure is an upper bound.
- Whether a fire was correct. One session invoked the `Skill` tool with `Bash` as the skill
  name, and that counts as a fire here.

**Rare is not dead.** A skill with no fires and no openings was never in a position to fire,
which says something about the work rather than about the skill. Twenty-nine skills are in that
group and they are reported in a separate table that is never added to the sixty-nine that had
openings.

## Running it

```bash
python3 -m skillfire inventory          # what is loaded and what it costs
python3 -m skillfire report             # measure this machine
python3 -m skillfire report --json      # the same as JSON
python3 scripts/build_docs.py --measure # refresh docs/measured.json and the page
```

Standard library only, Python 3.10 or newer. Transcripts are opened read only. Override the
locations with `SKILLFIRE_CLAUDE_HOME` and `CLAUDE_PROJECTS_DIR`.

## Verify

```bash
bash scripts/verify.sh
```

Every step runs against the synthetic machine in `skillfire/fixtures.py`, so verify passes on a
laptop that has never run Claude Code and gives the same answer from a clean clone in `/tmp`.

## What was reused

Two projects in this workspace already parse these transcripts and their conclusions were taken
rather than rediscovered. From `projects/session-search` (`sessionsearch/parse.py`): the record
shapes, that `message.content` is either a string or a list of typed blocks, that `tool_use` and
`tool_result` pair by id, that `isSidechain` marks a subagent turn and `isMeta` marks harness
injection, and the ISO timestamp handling. From `projects/session-fork`
(`session_fork/discover.py`): the transcript discovery shape, including the
`CLAUDE_PROJECTS_DIR` override. New here: skill event extraction, the inventory and its cost
model, the trigger vocabulary, and the closed-vocabulary rule that keeps prose out of the
output.

## Status

Pasted output of `bash scripts/verify.sh`:

```
PLACEHOLDER
```

## Unfinished

- **The counterfactual is weak and stays weak.** Twenty percent recall on ten known cases is
  measured, not estimated, but ten cases is a small sample and the confidence interval on it is
  wide. A stronger proxy would need an embedding model, or a labelled set of sessions, and both
  were out of scope for an S.
- **Availability is inferred, not observed.** Claude Code does not record which skills were
  offered in a given session, so exposure comes from install timestamps and is an upper bound.
  A hook writing the offered set per session would fix this properly and needs a config change.
- **Built-in skills are counted as fires but have no cost row.** `dataviz`, `loop`, `schedule`,
  `artifact-design` and `claude-api` ship inside the CLI rather than on disk, so their
  descriptions cannot be read and their standing cost is not in the 9,622 token figure. The
  real per-session cost is higher than reported.
- **Plugin commands are not skills and are not counted.** A plugin can also ship `commands/`,
  which have their own context cost. Only `SKILL.md` directories are in the inventory.
- **The token estimate is characters over four.** No tokeniser is used, and the figure is
  labelled as an estimate everywhere it appears.
- **One transcript directory only.** Sessions under a different `CLAUDE_PROJECTS_DIR`, or on
  another machine, are not merged.
