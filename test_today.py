import unittest

import today


class PercentRows(unittest.TestCase):
    def pcts(self, weights):
        return [pct for _, pct in today.percent_rows(weights)]

    def test_no_phantom_other(self):
        self.assertEqual(self.pcts({"a": 1, "b": 1, "c": 1}), [34, 33, 33])

    def test_sums_to_100(self):
        self.assertEqual(sum(self.pcts({name: 1 for name in "abcdef"})), 100)

    def test_small_tail_keeps_its_other_row(self):
        weights = {f"top{i}": 9.55 for i in range(10)} | {f"tail{i}": 0.5 for i in range(9)}
        rows = today.percent_rows(weights)
        self.assertEqual(rows[-1], ("Other", 4))
        self.assertEqual(sum(pct for _, pct in rows), 100)

    def test_no_languages_no_rows(self):
        self.assertEqual(today.percent_rows({}), [])


class TokenGate(unittest.TestCase):
    def test_repo_scope_is_matched_exactly(self):
        self.assertTrue(today.has_repo_scope("read:org, repo, read:user"))
        self.assertFalse(today.has_repo_scope("public_repo, read:user"))
        self.assertFalse(today.has_repo_scope(""))


class LangRows(unittest.TestCase):
    def test_long_name_is_cut_before_the_percent_column(self):
        svg = today.lang_rows([("Common Workflow Language", 5, None)], today.PALETTES["dark_mode.svg"])
        self.assertIn(">Common Workflow …<", svg)


if __name__ == "__main__":
    unittest.main()
