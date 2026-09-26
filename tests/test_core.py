import json
import threading
import unittest

from local_snapshotter_context import LocalSnapshotterContext, SnapshotError


class TestBasicAccess(unittest.TestCase):
    def setUp(self):
        self.ctx = LocalSnapshotterContext()

    def test_set_and_get(self):
        self.ctx.set("request_id", "req-123")
        self.assertEqual(self.ctx.get("request_id"), "req-123")

    def test_get_missing_returns_default(self):
        self.assertIsNone(self.ctx.get("missing"))
        self.assertEqual(self.ctx.get("missing", "fallback"), "fallback")

    def test_remove(self):
        self.ctx.set("a", 1)
        self.ctx.remove("a")
        self.assertIsNone(self.ctx.get("a"))

    def test_remove_missing_is_silent(self):
        # Should not raise.
        self.ctx.remove("never_set")

    def test_clear(self):
        self.ctx.set("a", 1)
        self.ctx.set("b", 2)
        self.ctx.clear()
        self.assertEqual(self.ctx.items(), {})

    def test_items_returns_copy(self):
        self.ctx.set("a", 1)
        d = self.ctx.items()
        d["a"] = 999
        self.assertEqual(self.ctx.get("a"), 1)

    def test_non_string_key_rejected(self):
        with self.assertRaises(TypeError):
            self.ctx.set(123, "x")  # type: ignore[arg-type]


class TestSerialization(unittest.TestCase):
    def setUp(self):
        self.ctx = LocalSnapshotterContext()

    def test_snapshot_prefix(self):
        self.ctx.set("k", "v")
        token = self.ctx.snapshot()
        self.assertTrue(token.startswith("LSC1:"))

    def test_round_trip_simple(self):
        self.ctx.set("request_id", "req-1")
        self.ctx.set("count", 3)
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.restore(token)
        self.assertEqual(other.get("request_id"), "req-1")
        self.assertEqual(other.get("count"), 3)

    def test_snapshot_is_stable_across_key_order(self):
        # Setting keys in different orders should yield the same token because
        # we serialize with sort_keys=True.
        ctx_a = LocalSnapshotterContext()
        ctx_a.set("a", 1)
        ctx_a.set("b", 2)

        ctx_b = LocalSnapshotterContext()
        ctx_b.set("b", 2)
        ctx_b.set("a", 1)

        self.assertEqual(ctx_a.snapshot(), ctx_b.snapshot())

    def test_restore_replaces_by_default(self):
        self.ctx.set("a", 1)
        self.ctx.set("b", 2)
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.set("b", 999)
        other.set("c", 3)
        other.restore(token)
        self.assertEqual(other.items(), {"a": 1, "b": 2})

    def test_restore_merge_mode(self):
        self.ctx.set("a", 1)
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.set("a", 999)
        other.set("b", 2)
        other.restore(token, merge=True)
        self.assertEqual(other.get("a"), 1)
        self.assertEqual(other.get("b"), 2)


class TestValueDomain(unittest.TestCase):
    def setUp(self):
        self.ctx = LocalSnapshotterContext()

    def test_nested_structures_round_trip(self):
        payload = {"user": {"id": 7, "roles": ["read", "write"]}, "flag": True}
        self.ctx.set("ctx", payload)
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.restore(token)
        self.assertEqual(other.get("ctx"), payload)

    def test_non_serializable_value_rejected_at_set_time(self):
        with self.assertRaises(SnapshotError):
            self.ctx.set("bad", object())

    def test_float_value_round_trips(self):
        # 0.1 + 0.2 is not exactly 0.3 in float; compare via repr to avoid a
        # floating-point equality assertion while still testing round-trip.
        value = 0.1 + 0.2
        self.ctx.set("x", value)
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.restore(token)
        self.assertEqual(repr(other.get("x")), repr(value))

    def test_none_value_round_trips(self):
        self.ctx.set("x", None)
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.restore(token)
        self.assertIsNone(other.get("x"))

    def test_unicode_value_round_trips(self):
        self.ctx.set("name", "Résumé")
        token = self.ctx.snapshot()

        other = LocalSnapshotterContext()
        other.restore(token)
        self.assertEqual(other.get("name"), "Résumé")


class TestTokenErrors(unittest.TestCase):
    def setUp(self):
        self.ctx = LocalSnapshotterContext()

    def test_restore_non_string_token(self):
        with self.assertRaises(SnapshotError):
            self.ctx.restore(12345)  # type: ignore[arg-type]

    def test_restore_bad_prefix(self):
        with self.assertRaises(SnapshotError):
            self.ctx.restore("XXX:{}")

    def test_restore_malformed_json(self):
        with self.assertRaises(SnapshotError):
            self.ctx.restore("LSC1:{not json}")

    def test_restore_non_object_body(self):
        # A JSON array is valid JSON but not a valid context body.
        token = "LSC1:" + json.dumps([1, 2, 3])
        with self.assertRaises(SnapshotError):
            self.ctx.restore(token)


class TestThreadIsolation(unittest.TestCase):
    def test_isolation_between_threads(self):
        ctx = LocalSnapshotterContext()
        ctx.set("who", "main")

        seen = {}

        def worker():
            # In the worker thread the store should start empty.
            seen["initial"] = ctx.items()
            ctx.set("who", "worker")
            seen["final"] = ctx.items()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertEqual(seen["initial"], {})
        self.assertEqual(seen["final"], {"who": "worker"})
        self.assertEqual(ctx.get("who"), "main")


if __name__ == "__main__":
    unittest.main()
