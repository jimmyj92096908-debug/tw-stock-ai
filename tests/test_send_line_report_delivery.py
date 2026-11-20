"""Network-free regression tests for existing daily LINE push de-duplication."""
import unittest
from datetime import date
from unittest.mock import patch

from src.send_line_report import send_report


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        if "SELECT 1 FROM public.line_messages" in sql:
            self.result = (1,) if params[0] in self.connection.event_ids else None
        elif "INSERT INTO public.line_messages" in sql:
            event_id, user_id, text = params
            self.connection.event_ids.add(event_id)
            self.connection.inserted.append((event_id, user_id, text))
        else:
            raise AssertionError("Unexpected SQL statement")

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self):
        self.event_ids = set()
        self.inserted = []
        self.commit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_calls += 1


class FakeResponse:
    def __init__(self, code):
        self.status_code = code


def sample():
    return {
        "trade_date": date(2026, 11, 19),
        "recipients": ["U-mock-not-a-person"],
    }


class DailyLineDeliveryTests(unittest.TestCase):
    def test_first_push_logs_and_repeat_skips_without_second_push(self):
        db = FakeConnection()
        with (
            patch("src.send_line_report.psycopg.connect", return_value=db),
            patch("src.send_line_report.requests.post",
                  return_value=FakeResponse(200)) as post,
        ):
            first = send_report("postgresql://localhost/fake", "dummy-token", sample(), "測試報告")
            repeated = send_report("postgresql://localhost/fake", "dummy-token", sample(), "測試報告")
        self.assertEqual((first, repeated), (1, 0))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(db.commit_calls, 1)
        self.assertEqual(len(db.inserted), 1)
        self.assertTrue(db.inserted[0][0].startswith("daily-report:2026-11-19:"))
        self.assertEqual(db.inserted[0][1], "U-mock-not-a-person")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer dummy-token")
        self.assertEqual(kwargs["json"]["to"], "U-mock-not-a-person")

    def test_push_http_failure_does_not_mark_event_as_sent(self):
        db = FakeConnection()
        with (
            patch("src.send_line_report.psycopg.connect", return_value=db),
            patch("src.send_line_report.requests.post",
                  return_value=FakeResponse(429)),
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                send_report("postgresql://localhost/fake", "dummy-token", sample(), "測試報告")
        self.assertEqual(db.commit_calls, 0)
        self.assertEqual(db.inserted, [])

    def test_network_failure_does_not_write_sent_marker(self):
        db = FakeConnection()
        with (
            patch("src.send_line_report.psycopg.connect", return_value=db),
            patch("src.send_line_report.requests.post",
                  side_effect=TimeoutError("fake network timeout")),
        ):
            with self.assertRaises(TimeoutError):
                send_report("postgresql://localhost/fake", "dummy-token", sample(), "測試報告")
        self.assertEqual(db.inserted, [])

    def test_bad_recipient_does_not_block_later_users_and_deduplicates_success(self):
        db = FakeConnection()
        rows = sample()
        rows["recipients"] = [
            "U-fake-undeliverable-1",
            "U-fake-deliverable",
            "U-fake-undeliverable-2",
        ]
        responses = [FakeResponse(400), FakeResponse(200), FakeResponse(404)]
        with (
            patch("src.send_line_report.psycopg.connect", return_value=db),
            patch("src.send_line_report.requests.post", side_effect=responses) as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "拒絕 2 位收件者"):
                send_report("postgresql://localhost/fake", "dummy-token", rows, "測試報告")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(db.commit_calls, 1)
        self.assertEqual(len(db.inserted), 1)
        self.assertEqual(db.inserted[0][1], "U-fake-deliverable")

        # A retry attempts only the failed recipients, not the delivered user.
        with (
            patch("src.send_line_report.psycopg.connect", return_value=db),
            patch("src.send_line_report.requests.post",
                  side_effect=[FakeResponse(200), FakeResponse(200)]) as post,
        ):
            self.assertEqual(
                send_report("postgresql://localhost/fake", "dummy-token", rows, "測試報告"),
                2,
            )
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(db.inserted), 3)

    def test_global_rate_limit_fails_fast_to_prevent_flooding(self):
        db = FakeConnection()
        rows = sample()
        rows["recipients"] = ["U-fake-1", "U-fake-2"]
        with (
            patch("src.send_line_report.psycopg.connect", return_value=db),
            patch("src.send_line_report.requests.post",
                  side_effect=[FakeResponse(429), FakeResponse(200)]) as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                send_report("postgresql://localhost/fake", "dummy-token", rows, "測試報告")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(db.inserted, [])

    def test_requires_token_and_preexisting_recipients(self):
        with self.assertRaisesRegex(RuntimeError, "LINE_CHANNEL_ACCESS_TOKEN"):
            send_report("postgresql://localhost/fake", "", sample(), "報告")
        no_users = sample()
        no_users["recipients"] = []
        with self.assertRaisesRegex(RuntimeError, "沒有可通知"):
            send_report("postgresql://localhost/fake", "dummy-token", no_users, "報告")


if __name__ == "__main__":
    unittest.main()
