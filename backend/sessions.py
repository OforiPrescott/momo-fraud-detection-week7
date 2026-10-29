"""In-memory store of analysed datasets (so threshold changes and case drill-down need no re-upload).

Each analysis belongs to the user who ran it; nobody else can read it. Each user keeps their most recent
MAX_PER_USER analyses, and the server as a whole keeps at most MAX_SESSIONS to bound memory."""
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_SESSIONS = int(os.environ.get("MOMO_MAX_SESSIONS", 24))
MAX_PER_USER = 3


@dataclass
class Session:
    id: str
    owner: int
    frame: object          # DataFrame: context + features + risk
    meta: dict
    curves: dict
    source: dict
    created: float = field(default_factory=time.time)


_store: "OrderedDict[str, Session]" = OrderedDict()
_lock = threading.Lock()


def put(owner, frame, meta, curves, source) -> Session:
    s = Session(uuid.uuid4().hex, owner, frame, meta, curves, source)
    with _lock:
        _store[s.id] = s
        mine = [k for k, v in _store.items() if v.owner == owner]
        for k in mine[:-MAX_PER_USER]:
            del _store[k]
        while len(_store) > MAX_SESSIONS:
            _store.popitem(last=False)
    return s


def get(sid: str, owner):
    with _lock:
        s = _store.get(sid)
        if not s or s.owner != owner:
            return None
        _store.move_to_end(sid)
        return s


def drop_owner(owner):
    with _lock:
        for k in [k for k, v in _store.items() if v.owner == owner]:
            del _store[k]
