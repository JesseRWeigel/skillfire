"""The guarantee this project has to keep: nothing from a transcript body reaches an output.

The fixture transcripts are loaded with credentials, a home path, a password, a doctor's name
and a medical detail. Every one of them must be absent from every rendering, from the JSON, and
from the fields of every object the scanner returns.
"""

import json
import os
import unittest

from skillfire import events, fixtures, redact, report

from tests import support


class Planted(unittest.TestCase):
    def setUp(self):
        self.rows, self.corpus, self.summary = support.analysis()
        self.planted = fixtures.planted_values()
        _, self.transcripts = support.machine()

    def test_the_fixtures_really_do_contain_the_planted_values(self):
        # A leak check against a corpus that never held the secret is a check of nothing.
        blob = ""
        for directory, _, names in os.walk(self.transcripts):
            for name in names:
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    blob += handle.read()
        for label, value in self.planted.items():
            self.assertIn(value, blob, f"{label} is not in the fixture corpus")

    def test_nothing_planted_reaches_the_text_report(self):
        text = report.render_text(self.rows, self.corpus, self.summary)
        for label, value in self.planted.items():
            self.assertNotIn(value, text, label)

    def test_nothing_planted_reaches_the_json_report(self):
        blob = report.render_json(self.rows, self.corpus, self.summary)
        for label, value in self.planted.items():
            self.assertNotIn(value, blob, label)
        json.loads(blob)

    def scanned(self):
        from skillfire import inventory, pipeline, triggers
        home, transcripts = support.machine()
        skills, _ = inventory.build(home=home)
        vocab = triggers.Vocabulary(triggers.build(skills))
        slash = pipeline.slash_map(skills)
        return [events.scan_file(path, vocab, slash) for path in events.find(transcripts)]

    def test_no_field_of_a_scanned_session_holds_transcript_prose(self):
        # Everything except the skill name itself. A skill name is a closed vocabulary in the
        # ordinary case and a shape constrained string in the worst case, and the next test
        # covers the worst case.
        for facts in self.scanned():
            blob = json.dumps({
                "session": facts.session,
                "manifest_reads": facts.manifest_reads,
                "turn_terms": [sorted(t) for t in facts.turn_terms],
                "matched": facts.matched,
            })
            for label, value in self.planted.items():
                self.assertNotIn(value, blob, f"{label} survived scan_file")

    def test_a_credential_shaped_skill_name_reaches_the_scanner_and_stops_at_the_scrubber(self):
        # A token is a legal skill name, so the structural rule cannot exclude it and saying
        # otherwise would be a false claim. This is the case the second layer exists for, and
        # the test asserts both halves: it gets in, and it does not get out.
        token = self.planted["github token"]
        names = {name for facts in self.scanned() for _, name, _ in facts.fires}
        self.assertIn(token, names)
        text = report.render_text(self.rows, self.corpus, self.summary)
        blob = report.render_json(self.rows, self.corpus, self.summary)
        self.assertNotIn(token, text)
        self.assertNotIn(token, blob)

    def test_a_user_skill_name_is_hashed_rather_than_printed(self):
        text = report.render_text(self.rows, self.corpus, self.summary)
        self.assertNotIn("my-private-workflow", text)
        self.assertIn("user-skill-", text)

    def test_a_plugin_skill_name_is_printed_as_is(self):
        self.assertEqual(redact.public_name("alpha:dither-images", "plugin"),
                         "alpha:dither-images")


class Scrub(unittest.TestCase):
    """The second layer, dormant while the first holds. Tested directly because it has to be."""

    def test_a_home_shaped_path_is_rewritten_wherever_the_repo_lives(self):
        # Not anchored on the running user's home, so this holds on a machine where the
        # checkout sits somewhere else entirely.
        self.assertNotIn("/home/someoneelse", redact.scrub("see /home/someoneelse/notes.txt"))
        self.assertNotIn("/Users/someoneelse", redact.scrub("see /Users/someoneelse/notes"))

    def test_the_running_home_is_collapsed(self):
        home = os.path.expanduser("~")
        self.assertNotIn(home, redact.scrub(f"file at {home}/thing"))

    def test_credential_shapes_are_masked(self):
        for label, value in fixtures.planted_values().items():
            if label in ("password", "personal", "home path"):
                continue
            self.assertNotIn(value, redact.scrub(f"key {value} end"), label)

    def test_scrub_leaves_ordinary_text_alone(self):
        self.assertEqual(redact.scrub("42 fires, 0 opportunities"), "42 fires, 0 opportunities")


if __name__ == "__main__":
    unittest.main()
