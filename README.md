# local_snapshotter_context

A small library that captures a thread-local dict of key-value pairs and serializes it into a token string suitable for propagation across process boundaries.

```python
from local_snapshotter_context import LocalSnapshotterContext

ctx = LocalSnapshotterContext()
ctx.set("request_id", "req-abc")
ctx.set("user_id", 42)

token = ctx.snapshot()  # 'LSC1:{...}'

# ...later, possibly in another thread or after a process restart...
restored = LocalSnapshotterContext()
restored.restore(token)
print(restored.get("request_id"))  # 'req-abc'
```

## Why

When you need to carry per-request metadata across a boundary the language can't span (a subprocess, a queue message, a log line), you need a stable string you can hand off. This library keeps a thread-local store so that concurrent requests in the same process don't collide, and gives you a single `snapshot()`/`restore(token)` pair to move the whole bag at once.

The trade-off: values are restricted to JSON-native types (dict, list, str, int/float, bool, None). This is deliberate — accepting arbitrary Python objects would require pickle, and pickle tokens are not safe to accept back from untrusted sources.

## Edge cases

- `restore(token)` replaces the current thread's store by default. Pass `merge=True` if you want the token's keys to overwrite only the keys it contains, leaving others untouched.
- The store is thread-local, not process-local. If you actually hand the token to another thread, call `restore` there explicitly; the token will not appear on its own.
- Setting a value that isn't JSON-serializable (e.g. a custom object) raises `SnapshotError` at `set` time, not later during `snapshot`.

## Exported names

- `LocalSnapshotterContext` — the context class. Methods: `set`, `get`, `remove`, `clear`, `items`, `snapshot`, `restore`.
- `SnapshotError` — raised on serialization or token-validation failures.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
