import unittest

from skillfire import inventory, triggers

from tests import support


class Tokens(unittest.TestCase):
    def test_unigrams_and_bigrams(self):
        found = triggers.tokens("Pull Request review")
        self.assertIn("pull", found)
        self.assertIn("pull request", found)
        self.assertIn("request review", found)

    def test_punctuation_breaks_a_bigram(self):
        self.assertNotIn("end start", triggers.tokens("end. start"))


class Terms(unittest.TestCase):
    def setUp(self):
        home, _ = support.machine()
        self.skills, _ = inventory.build(home=home)
        self.terms = triggers.build(self.skills)

    def test_distinctive_words_survive(self):
        self.assertIn("dithering", self.terms["alpha:dither-images"])
        self.assertIn("crontab", self.terms["gamma:late-arrival"])

    def test_stoplisted_filler_is_gone(self):
        for terms in self.terms.values():
            for filler in ("when", "using", "your", "adding"):
                self.assertNotIn(filler, terms)

    def test_a_word_shared_by_too_many_skills_is_dropped(self):
        # "workspace" is in five of the fixture descriptions. No stoplist would catch it, since
        # it is an ordinary content word, and that is exactly what the spread filter is for.
        holders = [name for name, skill in
                   ((s.name, s) for s in self.skills) if "workspace" in skill.description]
        self.assertGreater(len(holders), triggers.MAX_SKILLS_PER_TERM)
        for name, terms in self.terms.items():
            self.assertNotIn("workspace", terms, name)
            self.assertNotIn("use", terms, name)

    def test_a_term_too_short_to_discriminate_is_dropped(self):
        for terms in self.terms.values():
            for term in terms:
                if " " not in term:
                    self.assertGreaterEqual(len(term), triggers.MIN_TERM_LEN)


class Prune(unittest.TestCase):
    def setUp(self):
        home, _ = support.machine()
        skills, _ = inventory.build(home=home)
        self.vocab = triggers.Vocabulary(triggers.build(skills))

    def test_a_term_in_most_turns_is_dropped_as_filler(self):
        frequency = {term: 1 for term in self.vocab.terms}
        victim = sorted(self.vocab.terms)[0]
        frequency[victim] = 900
        kept, dropped = triggers.prune(self.vocab, frequency, 1000)
        self.assertIn(victim, dropped)
        self.assertTrue(all(victim not in terms for terms in kept.values()))

    def test_a_small_corpus_does_not_prune_everything(self):
        # On ten turns a ten percent ceiling would drop any term used twice. The floor exists
        # to stop that, and it is the bug that emptied two thirds of the vocabulary once.
        frequency = {term: 2 for term in self.vocab.terms}
        _, dropped = triggers.prune(self.vocab, frequency, 10)
        self.assertEqual(dropped, [])


class Match(unittest.TestCase):
    def test_one_shared_term_is_not_enough(self):
        matcher = triggers.Matcher({"a": ["alpha", "beta"], "b": ["gamma"]})
        self.assertEqual(matcher.match({"alpha"}), set())
        self.assertEqual(matcher.match({"alpha", "beta"}), {"a"})

    def test_a_skill_left_with_one_term_can_never_match(self):
        matcher = triggers.Matcher({"a": ["alpha"]})
        self.assertEqual(matcher.match({"alpha"}), set())


if __name__ == "__main__":
    unittest.main()
