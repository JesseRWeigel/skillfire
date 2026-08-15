import unittest

from tests import support


class Rows(unittest.TestCase):
    def setUp(self):
        self.rows, self.corpus, self.summary = support.analysis()

    def row(self, name):
        return self.rows[name]

    def test_a_fire_is_counted_against_the_skill_named(self):
        self.assertEqual(self.row("alpha:dither-images").fires, 1)
        self.assertEqual(self.row("beta:parquet-loader").fires, 2)

    def test_a_fire_naming_something_uninstalled_lands_in_the_corpus_not_a_row(self):
        self.assertEqual(self.corpus.fires_unknown_skill, 2)
        self.assertEqual(sum(r.fires for r in self.rows.values()),
                         self.summary["fires_matched_to_inventory"])

    def test_a_skill_installed_late_is_not_live_in_earlier_sessions(self):
        self.assertLess(self.row("gamma:late-arrival").sessions_live,
                        self.row("alpha:dither-images").sessions_live)

    def test_an_earlier_session_is_not_an_opportunity_for_a_later_skill(self):
        # s07 and s08 carry identical wording either side of the install date.
        self.assertEqual(self.row("gamma:late-arrival").opportunities, 1)

    def test_displacement_splits_by_whether_anything_else_fired(self):
        row = self.row("beta:lockfile-surgery")
        self.assertEqual(row.opportunities, 2)
        self.assertEqual(row.displaced_by_skill, 1)
        self.assertEqual(row.displaced_unassisted, 1)

    def test_opportunities_account_for_every_outcome(self):
        for row in self.rows.values():
            self.assertEqual(row.opportunities,
                             row.fires_in_opportunity + row.displaced_by_skill
                             + row.displaced_unassisted)

    def test_capture_rate_never_exceeds_one(self):
        for row in self.rows.values():
            if row.capture_rate is not None:
                self.assertLessEqual(row.capture_rate, 1.0)

    def test_rare_and_dead_are_different_classes(self):
        self.assertEqual(self.row("beta:never-relevant").verdict_class,
                         "never-fired-no-opening")
        self.assertEqual(self.row("beta:lockfile-surgery").verdict_class,
                         "never-fired-had-openings")

    def test_a_skill_that_fired_is_never_classed_as_dead(self):
        for row in self.rows.values():
            if row.fires:
                self.assertEqual(row.verdict_class, "fired")

    def test_harness_injected_text_creates_no_opportunity(self):
        # Every fixture mention of a spectrophotometer sits inside a system-reminder, a meta
        # record or a tool result. If any of those counted, this would not be zero.
        self.assertEqual(self.row("beta:never-relevant").opportunities, 0)

    def test_proxy_recall_is_reported_and_is_below_one(self):
        recall = self.summary["proxy_recall_on_real_fires"]
        self.assertIsNotNone(recall)
        self.assertLess(recall, 1.0)

    def test_standing_spend_is_cost_times_exposure(self):
        for row in self.rows.values():
            self.assertEqual(row.tokens_spent, row.est_tokens * row.sessions_live)

    def test_manifest_read_is_attributed_to_the_qualified_name(self):
        self.assertEqual(self.row("beta:lockfile-surgery").manifest_reads, 1)


if __name__ == "__main__":
    unittest.main()
