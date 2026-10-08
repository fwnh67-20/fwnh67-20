import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import activity  # noqa: E402
import render  # noqa: E402

PUSHED = "2026-10-08T21:11:46Z"


def fake_request(token, path, body=None):
    if path.startswith("/users/"):
        return [{"created_at": "2026-10-08T21:40:31Z", "repo": {"name": "owner/secret-client-repo"}}]
    if "repositories" in body["query"]:
        return {
            "data": {
                "viewer": {
                    "login": "owner",
                    "repositories": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"pushedAt": PUSHED, "owner": {"login": "owner"}, "primaryLanguage": {"name": "Kotlin"}},
                            {"pushedAt": "2026-10-01T00:00:00Z", "owner": {"login": "partner"}, "primaryLanguage": None},
                            {"pushedAt": "2025-01-01T00:00:00Z", "owner": {"login": "owner"}, "primaryLanguage": {"name": "Go"}},
                        ],
                    },
                }
            }
        }
    days = [{"date": f"2026-10-{d:02d}", "contributionCount": d} for d in range(1, 10)]
    return {"data": {"viewer": {"contributionsCollection": {"contributionCalendar": {"totalContributions": 999, "weeks": [{"contributionDays": days}]}}}}}


class ActivityTest(unittest.TestCase):
    def collect(self):
        with mock.patch.object(activity, "request", side_effect=fake_request):
            return activity.collect("token", datetime(2026, 10, 9, tzinfo=timezone.utc))

    def test_only_aggregates_leave_the_collector(self):
        data = self.collect()
        self.assertEqual(
            set(data),
            {"generatedAt", "lastActiveAt", "windowDays", "contributionsYear", "contributionsWindow", "daily", "dailyEnd", "activeRepositories", "languages"},
        )
        serialised = json.dumps(data)
        for secret in ("secret-client-repo", "owner", "partner"):
            self.assertNotIn(secret, serialised)

    def test_window_and_last_active(self):
        data = self.collect()
        self.assertEqual(data["lastActiveAt"], "2026-10-08T21:40:31+00:00")
        self.assertEqual(data["activeRepositories"], 2)
        self.assertEqual(data["languages"], ["Kotlin"])
        self.assertEqual(len(data["daily"]), activity.WINDOW_DAYS)
        self.assertEqual(data["contributionsWindow"], sum(range(1, 10)))


class RenderTest(unittest.TestCase):
    def test_runs_keep_spaces_between_styled_words(self):
        runs = [("since ", False), ("2007", True), (". ", False), ("13 years", True), (" in", False)]
        lines = render.wrap_runs(runs, "display", 46, 10_000)
        self.assertEqual("".join(text for text, _ in lines[0]), "since 2007. 13 years in")

    def test_wrapped_lines_fit(self):
        text = render.CONTENT["person"]["summary"]
        for line in render.wrap(text, "bold", 24, 300):
            self.assertLessEqual(render.measure(line, "bold", 24), 300)

    def test_activity_card_tolerates_missing_data(self):
        svg, alt = render.activity("light", "narrow", {})
        self.assertIn("Last active · unavailable", alt)
        self.assertTrue(svg.startswith("<svg"))

    def test_static_output_is_current(self):
        with mock.patch.object(sys, "argv", ["render.py", "--check"]):
            render.main()  # exits with the stale file list when output is out of date


if __name__ == "__main__":
    unittest.main()
