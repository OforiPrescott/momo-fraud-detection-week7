"""In-memory store of analysed datasets (so threshold changes and case drill-down need no re-upload)."""
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_SESSIONS = 6


@dataclass
class Session:
    id: str
    frame: object          # DataFrame: context + features + risk
    meta: dict
    curves: dict
    source: dict
    created: float = field(default_factory=time.time)


_store: "OrderedDict[str, Session]" = OrderedDict()
_lock = threading.Lock()


def put(frame, meta, curves, source) -> Session:
    s = Session(uuid.uuid4().hex[:12], frame, meta, curves, source)
    with _lock:
        _store[s.id] = s
        while len(_store) > MAX_SESSIONS:
            _store.popitem(last=False)
    return s


def get(sid: str):
    with _lock:
        s = _store.get(sid)
        if s:
            _store.move_to_end(sid)
        return s
