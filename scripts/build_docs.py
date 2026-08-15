#!/usr/bin/env python3
"""Generate docs/index.html from docs/measured.json.

    build_docs.py --measure    rescan this machine and rewrite docs/measured.json
    build_docs.py              rebuild docs/index.html from the committed measurements
    build_docs.py --check      rebuild in memory and fail if the published page has drifted

The page is data, so `--check` can rebuild it and fail when the published page no longer matches
the code that produced it. The measurements are committed separately from the page because a
machine without a Claude Code history, which is every CI runner, cannot regenerate them, and a
page that silently rebuilds itself from an empty scan would publish zeroes and look fine.

Nothing written here comes from a transcript body. `docs/measured.json` holds skill names,
integer counts and one date range, and it goes through the same scrubber as every other output.
"""

from __future__ import annotations

import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DOCS = os.path.join(ROOT, "docs")
DATA = os.path.join(DOCS, "measured.json")
PAGE = os.path.join(DOCS, "index.html")

STYLE = """
:root{color-scheme:light dark;--bg:#fbfaf8;--fg:#191a1c;--muted:#5d626a;--line:#e4e5e8;
  --card:#fff;--bad:#a83232;--warn:#8a6300;--good:#2a6b40}
@media (prefers-color-scheme:dark){:root{--bg:#131416;--fg:#e9e7e3;--muted:#8f959d;
  --line:#25282c;--card:#191b1e;--bad:#e08a8a;--warn:#d8ae5a;--good:#7fc79a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.6 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:54rem;margin:0 auto;padding:3rem 1.25rem 4rem}
h1{font-size:clamp(1.9rem,5vw,2.5rem);margin:0 0 .3rem;letter-spacing:-.03em}
h2{font-size:1.1rem;margin:2.4rem 0 .7rem;padding-bottom:.35rem;
  border-bottom:1px solid var(--line)}
p{color:var(--muted);max-width:42rem}
.lede{color:var(--fg);font-size:1.05rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.8rem;
  margin:1.5rem 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:.9rem 1rem;
  min-width:0}
.stat b{display:block;font-size:1.7rem;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.stat span{color:var(--muted);font-size:.8rem}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.87rem;min-width:38rem}
th,td{text-align:left;padding:.35rem .55rem;border-bottom:1px solid var(--line);
  vertical-align:top}
th{color:var(--muted);font-weight:600}td.num{font-variant-numeric:tabular-nums;text-align:right}
code{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:.08rem .3rem;
  font-size:.85em}
.bad{color:var(--bad);font-weight:600}.warn{color:var(--warn);font-weight:600}
.good{color:var(--good);font-weight:600}
ul{color:var(--muted);max-width:42rem}
footer{margin-top:3rem;color:var(--muted);font-size:.85rem}
"""


def measure_now() -> dict:
    from skillfire import pipeline, redact, report  # noqa: E402
    from datetime import datetime, timezone

    rows, corpus, summary = pipeline.run()
    payload = json.loads(report.render_json(rows, corpus, summary))
    payload["generated"] = {
        "corpus_first": datetime.fromtimestamp(corpus.first_ts, timezone.utc).strftime("%Y-%m-%d")
        if corpus.first_ts else "",
        "corpus_last": datetime.fromtimestamp(corpus.last_ts, timezone.utc).strftime("%Y-%m-%d")
        if corpus.last_ts else "",
    }
    return json.loads(redact.scrub(json.dumps(payload, indent=2, sort_keys=True)))


def cell(value):
    return f'<td class="num">{html.escape(str(value))}</td>'


def render(data: dict) -> str:
    summary = data["summary"]
    corpus = data["corpus"]
    generated = data.get("generated", {})
    rows = data["skills"]

    fired = [r for r in rows if r["class"] == "fired"]
    openings = [r for r in rows if r["class"] == "never-fired-had-openings"]
    silent = [r for r in rows if r["class"] == "never-fired-no-opening"]
    recall = summary.get("proxy_recall_on_real_fires")
    recall_text = "not measurable" if recall is None else f"{recall * 100:.0f}%"

    def table(items, note):
        if not items:
            return f"<p>None.</p>"
        head = ("<div class=wrap><table><thead><tr><th>skill<th>tokens<th>sessions live"
                "<th>fires<th>openings<th>displaced<th>capture<th>spend</tr></thead><tbody>")
        body = []
        for row in items:
            rate = row["capture_rate"]
            rate_text = "-" if rate is None else f"{rate * 100:.0f}%"
            displaced = row["displaced_by_skill"] + row["displaced_unassisted"]
            body.append("<tr><td>" + html.escape(row["skill"])
                        + cell(row["est_tokens"]) + cell(row["sessions_live"])
                        + cell(row["fires"]) + cell(row["opportunities"]) + cell(displaced)
                        + cell(rate_text) + cell(row["tokens_spent"]) + "</tr>")
        return f"<p>{note}</p>" + head + "".join(body) + "</tbody></table></div>"

    span = ""
    if generated.get("corpus_first"):
        span = (f" spanning {html.escape(generated['corpus_first'])} to "
                f"{html.escape(generated['corpus_last'])}")

    parts = [
        "<title>skillfire</title>",
        f"<style>{STYLE}</style>",
        "<main>",
        "<h1>skillfire</h1>",
        "<p class=lede>Every installed skill puts its name and description into the system "
        "prompt of every session, whether or not it is ever used. This is what that cost bought "
        f"on one real machine: {corpus['sessions']} Claude Code transcripts{span}.</p>",

        "<div class=grid>",
        f"<div class=stat><b>{summary['skills']}</b><span>skills loaded every session</span>"
        "</div>",
        f"<div class=stat><b>{summary['standing_tokens_per_session']:,}</b>"
        "<span>estimated tokens of description, per session</span></div>",
        f"<div class=stat><b>{summary['fires_matched_to_inventory']}</b>"
        "<span>times any of them actually fired</span></div>",
        f"<div class=stat><b>{summary['never_fired_had_openings'] + summary['never_fired_no_opening']}"
        "</b><span>never fired once</span></div>",
        "</div>",

        "<h2>What the counterfactual can and cannot see</h2>",
        "<p>Counting fires is easy. The number that would say a skill is dead weight is the one "
        "where its situation arose and something else was used, and a transcript has no field "
        "for what the model considered and passed over. The proxy used here is lexical: each "
        "skill's own frontmatter description, which is the only text about it in front of the "
        "model when it chooses, is reduced to distinctive terms, and a user turn carrying two "
        "or more of them counts as an opening.</p>",
        f"<p>The proxy is checked against the cases where the answer is known. Of the "
        f"{summary['fire_sessions']} sessions that really did fire a skill, "
        f"{summary['fire_sessions_flagged_as_opportunity']} were flagged as an opening for the "
        f"skill that fired, a recall of <b>{recall_text}</b>. Read the opening counts below "
        f"with that in mind. They are a weak signal, and the honest reading is that they bound "
        f"the question rather than settle it.</p>",
        "<p>A skill that fires rarely because its situation is rare is not dead weight. That is "
        "why the two never-fired groups below are separate tables and are never added "
        "together.</p>",

        "<h2>Fired at least once</h2>",
        table(fired, f"{len(fired)} of {summary['skills']}."),

        "<h2>Never fired, and the wording never came up either</h2>",
        table(silent, f"{len(silent)} skills. Nothing here says the skill is bad. It says the "
                      f"situation it is for did not appear in this corpus, or that the proxy "
                      f"could not see it when it did."),

        "<h2>Never fired, though the wording did come up</h2>",
        table(openings, f"{len(openings)} skills. These are the candidates for dead weight, "
                        f"subject to the recall caveat above."),

        "<h2>Corpus</h2>",
        "<div class=wrap><table><tbody>",
    ]
    for label, key in (("transcripts", "sessions"), ("user turns", "user_turns"),
                       ("sidechain user turns", "sidechain_user_turns"),
                       ("tool calls", "tool_calls"),
                       ("sessions that fired anything", "sessions_with_a_fire"),
                       ("fires of any kind", "fires_total"),
                       ("fires naming something not installed", "fires_unknown_skill"),
                       ("unparseable JSONL lines", "bad_json")):
        parts.append(f"<tr><td>{label}{cell(corpus[key])}</tr>")
    parts.append(f"<tr><td>estimated standing spend, all sessions"
                 f"{cell(f'{summary['standing_tokens_spent_estimate']:,} tokens')}</tr>")
    parts.append("</tbody></table></div>")
    parts.append(
        "<footer>Generated by <code>scripts/build_docs.py</code> from "
        "<code>docs/measured.json</code>. No transcript text is read into either file. "
        "Token counts are characters over four, an estimate.</footer>")
    parts.append("</main>")
    return "\n".join(parts) + "\n"


def main(argv) -> int:
    if "--measure" in argv:
        os.makedirs(DOCS, exist_ok=True)
        data = measure_now()
        if not data["corpus"]["sessions"]:
            print("FAIL no transcripts found, so this would publish a page full of zeroes")
            return 1
        with open(DATA, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"wrote {os.path.relpath(DATA, ROOT)} from "
              f"{data['corpus']['sessions']} transcripts")

    if not os.path.isfile(DATA):
        print(f"FAIL {os.path.relpath(DATA, ROOT)} does not exist. Run with --measure on a "
              f"machine that has a Claude Code history.")
        return 1
    with open(DATA, encoding="utf-8") as handle:
        data = json.load(handle)
    page = render(data)

    if "--check" in argv:
        if not os.path.isfile(PAGE):
            print(f"FAIL {os.path.relpath(PAGE, ROOT)} does not exist")
            return 1
        with open(PAGE, encoding="utf-8") as handle:
            current = handle.read()
        if current != page:
            print("FAIL the published page does not match what the data would generate now")
            return 1
        print(f"  the published page matches the data ({len(page)} bytes)")
        return 0

    os.makedirs(DOCS, exist_ok=True)
    with open(PAGE, "w", encoding="utf-8") as handle:
        handle.write(page)
    print(f"wrote {os.path.relpath(PAGE, ROOT)} ({len(page)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
