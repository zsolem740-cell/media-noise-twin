"""Közös segédek: idő, azonosító, titokmaszkolás, újrapróbálás (exponenciális visszalépés jitterrel)."""
from __future__ import annotations

import logging
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, TypeVar

T = TypeVar("T")
ISO = "%Y-%m-%dT%H:%M:%S.%fZ"      # rögzített, UTC, rendezhető szöveg (SQLite és PostgreSQL alatt is összehasonlítható)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(ISO)


def parse_iso(s: str | None) -> datetime | None:
    return datetime.strptime(s, ISO).replace(tzinfo=timezone.utc) if s else None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


_SECRET_PATTERNS = [
    re.compile(r"apify_api_[A-Za-z0-9]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{8,}"),
    re.compile(r"(?i)(token|api[_-]?key|secret|password)(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]{6,})"),
]


def redact(text: str) -> str:
    out = str(text)
    out = _SECRET_PATTERNS[0].sub("***", out)
    out = _SECRET_PATTERNS[1].sub("Bearer ***", out)
    out = _SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}***", out)
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not any(isinstance(f, RedactingFilter) for f in log.filters):
        log.addFilter(RedactingFilter())
    return log


class RetryableError(Exception):
    """Átmeneti hiba: az újrapróbálás szabályos."""


class UncertainOutcome(Exception):
    """A művelet kimenetele bizonytalan (pl. időtúllépés kérés után). Először állapotot kell ellenőrizni, vakon nem indítunk újat."""


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """Teljes jitter: véletlen érték 0 és min(cap, base*2^attempt) között."""
    r = rng or random
    return r.uniform(0, min(cap, base * (2 ** attempt)))


def with_retry(fn: Callable[[], T], *, max_retries: int, base: float, cap: float,
               sleep: Callable[[float], None], should_stop: Callable[[], bool] = lambda: False,
               rng: random.Random | None = None) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except RetryableError:
            if attempt >= max_retries or should_stop():
                raise
            sleep(backoff_delay(attempt, base, cap, rng))
            attempt += 1
