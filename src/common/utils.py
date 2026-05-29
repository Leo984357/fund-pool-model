from __future__ import annotations
import functools
import random
import time
from datetime import date, datetime
from typing import Iterable, List, TypeVar

T = TypeVar("T")


def log(*args):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]", *args)


def today_ymd() -> str:
    return date.today().isoformat()


def norm_code(x) -> str:
    """Normalize fund code to 6-digit string."""
    if x is None:
        return ""
    s = str(x).strip()
    if s == "":
        return s
    try:
        if s.replace(".", "", 1).isdigit() and s.count(".") <= 1:
            v = int(float(s))
            return str(v).zfill(6)
    except Exception:
        pass
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits:
        v = int(digits)
        return str(v).zfill(6) if v < 10**6 else digits
    return s


def chunked(seq: Iterable[T], n: int) -> Iterable[List[T]]:
    buf: List[T] = []
    for x in seq:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf


def retry(exceptions=(Exception,), tries=3, base_delay=1.0, jitter=0.2):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            for i in range(tries):
                try:
                    return fn(*a, **k)
                except exceptions as e:
                    if i == tries - 1:
                        raise
                    sleep = base_delay * (2**i) + random.random() * jitter
                    log(f"retry {fn.__name__}: {e}, sleep {sleep:.1f}s")
                    time.sleep(sleep)
        return wrapper
    return deco
