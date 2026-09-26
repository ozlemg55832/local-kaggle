import json
import threading
from typing import Any, Dict, Optional


class SnapshotError(Exception):
    """Raised when a snapshot cannot be captured or restored.

    We use a dedicated exception type rather than re-raising ValueError so
    callers can distinguish propagation failures from genuinely bad caller
    arguments (e.g. passing None where a token string was expected).
    """


class LocalSnapshotterContext:
    """A thread-local store of key-value pairs with round-trippable tokens.

    The store is thread-local by design: in many server runtimes each request
    is handled on its own thread (or thread pool member), and we want one
    request's baggage to be invisible to another. If you actually need
    cross-thread propagation you must serialize on the sending thread and
    restore on the receiving thread explicitly.

    Serialization uses JSON because the value domain is deliberately limited
    to JSON-native types (dict, list, str, int/float, bool, None). Supporting
    arbitrary Python objects would force us into a pickle-based scheme, and
    pickle tokens are not safe to accept from untrusted sources. We trade
    generality for safety.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _data(self) -> Dict[str, Any]:
        if not hasattr(self._local, "data"):
            self._local.data = {}
        return self._local.data

    @staticmethod
    def _encode(payload: Dict[str, Any]) -> str:
        # sort_keys for stable, comparable tokens; ensure_ascii for byte-level
        # determinism across locales.
        body = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return "LSC1:" + body

    @staticmethod
    def _decode(token: str) -> Dict[str, Any]:
        if not isinstance(token, str):
            raise SnapshotError("token must be a string")
        prefix = "LSC1:"
        if not token.startswith(prefix):
            raise SnapshotError("unrecognized token prefix")
        body = token[len(prefix):]
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SnapshotError("malformed token body") from exc
        if not isinstance(decoded, dict):
            raise SnapshotError("token body is not a JSON object")
        # JSON object keys are always strings, but validate defensively so we
        # never store a non-string key downstream.
        for k in decoded:
            if not isinstance(k, str):
                raise SnapshotError("token contains non-string key")
        return decoded

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Set a single key in the current thread's context.

        Values must be JSON-serializable; we check eagerly so that a failure
        surfaces at the call site rather than later during `snapshot`.
        """
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        try:
            json.dumps(value, ensure_ascii=True)
        except (TypeError, ValueError) as exc:
            raise SnapshotError("value is not serializable") from exc
        self._data()[key] = value

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        return self._data().get(key, default)

    def remove(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        self._data().pop(key, None)

    def clear(self) -> None:
        self._data().clear()

    def items(self) -> Dict[str, Any]:
        """Return a shallow copy of the current thread's pairs.

        Copying avoids callers mutating the live store through the returned
        dict. Values themselves are not deep-copied; mutating a mutable value
        in the returned dict will still affect the store's value.
        """
        return dict(self._data())

    def snapshot(self) -> str:
        """Serialize the current thread's context into a token string."""
        return self._encode(self._data())

    def restore(self, token: str, *, merge: bool = False) -> None:
        """Replace (or merge into) the current thread's context from a token.

        With merge=False (default) the current store is cleared before
        loading the token's contents. With merge=True the token's pairs
        overwrite only the keys it contains.
        """
        decoded = self._decode(token)
        if not merge:
            self._data().clear()
        self._data().update(decoded)
