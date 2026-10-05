import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("AUTHENTIK_TOKEN", "test-token")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import monitor  # noqa: E402


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"pagination": {"count": 2}, "results": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._body


class TestApi(unittest.TestCase):
    def test_every_endpoint_has_a_trailing_slash(self):
        """Current Authentik 404s URLs without one, and every metric then reads 0."""
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return FakeResp()

        with mock.patch.object(monitor.SESSION, "get", side_effect=fake_get):
            monitor.collect_metrics()
        self.assertTrue(seen)
        for u in seen:
            self.assertTrue(u.endswith("/"), f"no trailing slash: {u}")

    def test_outposts_use_the_instances_endpoint(self):
        seen = []
        with mock.patch.object(monitor.SESSION, "get", side_effect=lambda u, **k: (seen.append(u), FakeResp())[1]):
            monitor.collect_metrics()
        self.assertTrue(any("outposts/instances/" in u for u in seen), seen)
        self.assertFalse(any("outposts/outposts" in u for u in seen), seen)

    def test_failed_calls_are_counted_not_reported_as_zero_quietly(self):
        with mock.patch.object(monitor.SESSION, "get", return_value=FakeResp(404)):
            m = monitor.collect_metrics()
        self.assertGreater(m["api_failures"], 0)
        self.assertEqual(m["users_total"], 0)  # still 0, but now flagged unreliable

    def test_healthy_run_reports_no_failures(self):
        with mock.patch.object(monitor.SESSION, "get", return_value=FakeResp()):
            m = monitor.collect_metrics()
        self.assertEqual(m["api_failures"], 0)
        self.assertEqual(m["users_total"], 2)

    def test_failure_metric_is_pushed(self):
        captured = {}
        with mock.patch.object(monitor.requests, "post", side_effect=lambda u, **k: (captured.update(data=k["data"]), FakeResp())[1]):
            monitor.push_metrics({**{k: 0 for k in ("users_total", "users_active", "users_superuser", "logins", "login_failures",
                                                     "password_changes", "applications", "providers", "groups")},
                                  "outposts": [], "api_failures": 3})
        self.assertIn("iib_api_failed_calls 3 ", captured["data"])


if __name__ == "__main__":
    unittest.main()
