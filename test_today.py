import json
import unittest
from unittest import mock

import today


class FakeResponse:
    def __init__(self, scopes, body):
        self.headers = {"X-OAuth-Scopes": scopes}
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def api(scopes, body):
    return mock.patch("urllib.request.urlopen", lambda *a, **k: FakeResponse(scopes, body))


class TokenGate(unittest.TestCase):
    def test_repo_scope_is_matched_exactly(self):
        self.assertTrue(today.has_repo_scope("read:org, repo, read:user"))
        self.assertFalse(today.has_repo_scope("public_repo, read:user"))
        self.assertFalse(today.has_repo_scope(""))

    def test_graphql_refuses_a_token_without_repo(self):
        with api("public_repo", {"data": {}}), self.assertRaises(SystemExit):
            today.graphql("query", {})

    def test_fetch_refuses_another_users_token(self):
        profile = {"viewer": {"login": "someone-else"}, "user": {}}
        with mock.patch("today.graphql", return_value=profile), self.assertRaises(SystemExit):
            today.fetch_stats()


class FetchStats(unittest.TestCase):
    def test_each_total_comes_from_its_own_field(self):
        year = today.datetime.now(today.timezone.utc).year
        profile = {
            "viewer": {"login": today.USERNAME},
            "user": {
                "createdAt": f"{year}-01-01T00:00:00Z",
                "pullRequests": {"totalCount": 7},
                "public": {"nodes": [{"stargazerCount": 2}, {"stargazerCount": 3}]},
            },
        }
        edges = [
            {"size": 3, "node": {"name": "Rust", "color": "#dea584"}},
            {"size": 1, "node": {"name": "Shell", "color": None}},
        ]
        window = {"user": {"contributionsCollection": {
            "totalCommitContributions": 10,
            "restrictedContributionsCount": 4,
            "contributionCalendar": {"totalContributions": 20},
            "commitContributionsByRepository": [
                {"contributions": {"totalCount": 10}, "repository": {"languages": {"edges": edges}}},
            ],
        }}}
        with mock.patch("today.graphql", side_effect=[profile, window]):
            stats = today.fetch_stats()
        self.assertEqual(stats.pop("languages"), [("Rust", 75, "#dea584"), ("Shell", 25, None)])
        self.assertEqual(stats, {"stars": 5, "contributions": 20, "commits": 10, "prs_merged": 7, "hidden": 4})


class ErrorPath(unittest.TestCase):
    def exit_text(self, errors):
        with api("repo", {"errors": errors}), self.assertRaises(SystemExit) as caught:
            today.graphql("query", {})
        return str(caught.exception)

    def test_message_never_reaches_the_log(self):
        text = self.exit_text([{"type": "FORBIDDEN", "message": "private-org denied"}])
        self.assertIn("FORBIDDEN", text)
        self.assertNotIn("private-org", text)

    def test_untyped_error_still_gets_a_label(self):
        self.assertIn("untyped", self.exit_text([{"message": "private-org timed out"}]))


class PercentRows(unittest.TestCase):
    def pcts(self, weights):
        return [pct for _, pct in today.percent_rows(weights)]

    def test_no_phantom_other(self):
        self.assertEqual(self.pcts({"a": 1, "b": 1, "c": 1}), [34, 33, 33])

    def test_sums_to_100(self):
        self.assertEqual(sum(self.pcts({name: 1 for name in "abcdef"})), 100)

    def test_leftover_points_go_to_the_largest_remainders(self):
        weights = {f"top{i}": 9.55 for i in range(10)} | {f"tail{i}": 0.5 for i in range(9)}
        rows = today.percent_rows(weights)
        self.assertEqual([pct for _, pct in rows], [10] * 6 + [9] * 4 + [4])
        self.assertEqual(rows[-1][0], "Other")

    def test_tiny_tail_keeps_its_other_row(self):
        weights = {f"top{i}": 10 for i in range(10)} | {"tail": 0.001}
        self.assertEqual(today.percent_rows(weights)[-1], ("Other", 0))

    def test_no_languages_no_rows(self):
        self.assertEqual(today.percent_rows({}), [])


class LangRows(unittest.TestCase):
    def row(self, name):
        return today.lang_rows([(name, 5, None)], today.PALETTES["dark_mode.svg"])

    def test_long_name_is_cut_before_the_percent_column(self):
        self.assertIn(">Common Workflow…<", self.row("Common Workflow Language"))

    def test_name_that_fits_is_kept_whole(self):
        self.assertIn(">Visual Basic .NET<", self.row("Visual Basic .NET"))


if __name__ == "__main__":
    unittest.main()
