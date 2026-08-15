import os
import unittest

from skillfire import events, inventory, pipeline, triggers

from tests import support


class Names(unittest.TestCase):
    def test_a_well_shaped_name_survives(self):
        self.assertEqual(events.safe_name("plugin:skill_name-2"), "plugin:skill_name-2")

    def test_anything_else_becomes_one_fixed_label(self):
        for bad in ("has spaces", "", None, 17, "x" * 200, "-leading"):
            self.assertEqual(events.safe_name(bad), events.UNRECOGNISED)


class Cleaning(unittest.TestCase):
    def test_system_reminders_are_removed(self):
        text = events.clean_user_text("before <system-reminder>secret listing</system-reminder> "
                                      "after")
        self.assertNotIn("secret listing", text)
        self.assertIn("before", text)
        self.assertIn("after", text)

    def test_local_command_output_is_removed(self):
        text = events.clean_user_text("a <local-command-stdout>x y z</local-command-stdout> b")
        self.assertNotIn("x y z", text)


class Scan(unittest.TestCase):
    def setUp(self):
        home, self.transcripts = support.machine()
        skills, _ = inventory.build(home=home)
        self.vocab = triggers.Vocabulary(triggers.build(skills))
        self.slash = pipeline.slash_map(skills)
        self.by_file = {}
        for path in events.find(self.transcripts):
            self.by_file[os.path.basename(path)] = events.scan_file(path, self.vocab, self.slash)

    def facts(self, prefix):
        for name, value in self.by_file.items():
            if name.startswith(prefix):
                return value
        raise AssertionError(f"no fixture session starting {prefix}")

    def test_a_skill_tool_call_is_a_fire(self):
        self.assertEqual(self.facts("s01").fired_names, {"alpha:dither-images"})

    def test_a_slash_command_naming_a_skill_is_a_fire(self):
        self.assertEqual(self.facts("s06").fired_names, {"beta:parquet-loader"})

    def test_a_manifest_read_is_recorded_separately_from_a_fire(self):
        facts = self.facts("s06")
        self.assertEqual(facts.manifest_reads, ["lockfile-surgery"])
        self.assertNotIn("beta:lockfile-surgery", facts.fired_names)

    def test_a_malformed_skill_name_is_replaced_not_printed(self):
        names = self.facts("s05").fired_names
        self.assertIn(events.UNRECOGNISED, names)
        self.assertIn("builtin-only-skill", names)

    def test_session_id_is_a_hash_and_not_the_path(self):
        for name, facts in self.by_file.items():
            self.assertNotIn("/", facts.session)
            self.assertNotIn(name, facts.session)

    def test_bad_json_is_counted_not_fatal(self):
        self.assertEqual(self.facts("s09").bad_json, 1)

    def test_harness_injections_are_not_user_turns(self):
        # s09 has six user shaped records; only the sidechain one and the aws key one are
        # real requests. The reminder, the meta record and the tool result are not.
        facts = self.facts("s09")
        self.assertEqual(facts.user_turns, 2)
        self.assertEqual(facts.sidechain_user_turns, 1)

    def test_every_term_kept_comes_from_the_closed_vocabulary(self):
        for facts in self.by_file.values():
            for terms in facts.turn_terms:
                self.assertTrue(set(terms) <= self.vocab.terms)

    def test_a_session_with_no_timestamps_still_parses(self):
        self.assertEqual(self.facts("s10").first_ts, 0.0)
        self.assertEqual(self.facts("s10").user_turns, 1)


if __name__ == "__main__":
    unittest.main()
