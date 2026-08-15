import unittest

from skillfire import inventory

from tests import support


class Frontmatter(unittest.TestCase):
    def test_reads_key_and_value(self):
        fields = inventory.parse_frontmatter("---\nname: x\ndescription: hello there\n---\nbody")
        self.assertEqual(fields["name"], "x")
        self.assertEqual(fields["description"], "hello there")

    def test_folds_a_continued_value(self):
        text = "---\ndescription: first line\n  second line\nname: y\n---\n"
        self.assertEqual(inventory.parse_frontmatter(text)["description"],
                         "first line second line")

    def test_strips_matching_quotes(self):
        text = '---\ndescription: "quoted value"\n---\n'
        self.assertEqual(inventory.parse_frontmatter(text)["description"], "quoted value")

    def test_no_frontmatter_is_empty(self):
        self.assertEqual(inventory.parse_frontmatter("# just a heading\n"), {})

    def test_unterminated_frontmatter_is_empty(self):
        self.assertEqual(inventory.parse_frontmatter("---\ndescription: x\n"), {})


class Build(unittest.TestCase):
    def setUp(self):
        home, _ = support.machine()
        self.skills, self.stats = inventory.build(home=home)
        self.by_name = {s.name: s for s in self.skills}

    def test_finds_every_enabled_plugin_skill(self):
        for name in ("alpha:dither-images", "beta:parquet-loader", "gamma:late-arrival"):
            self.assertIn(name, self.by_name)

    def test_a_disabled_plugin_costs_nothing_and_is_excluded(self):
        self.assertNotIn("delta:switched-off", self.by_name)
        self.assertEqual(self.stats.disabled_on_disk, 1)

    def test_user_skills_are_found_and_labelled(self):
        self.assertEqual(self.by_name["my-private-workflow"].origin, "user")

    def test_install_time_is_carried_through(self):
        early = self.by_name["alpha:dither-images"].available_from
        late = self.by_name["gamma:late-arrival"].available_from
        self.assertGreater(late, early)

    def test_standing_cost_counts_name_and_description_only(self):
        skill = self.by_name["alpha:dither-images"]
        self.assertEqual(skill.desc_chars, len(skill.name) + len(skill.description))
        cost = inventory.standing_cost(self.skills)
        self.assertEqual(cost["skills"], len(self.skills))
        self.assertEqual(cost["description_chars"], sum(s.desc_chars for s in self.skills))

    def test_body_text_is_not_counted(self):
        # The SKILL.md bodies say "Body text". If a body were counted the estimate would
        # include it, and the whole cost model would be wrong.
        self.assertNotIn("Body text", self.by_name["alpha:dither-images"].description)


if __name__ == "__main__":
    unittest.main()
