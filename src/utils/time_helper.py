"""ISO UTC konvertálás és magyar relatív idő."""
import time
from datetime import datetime, timezone

from dateutil import parser as dtparser


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso_utc(value) -> str | None:
    """struct_time / datetime / string -> 'YYYY-MM-DDTHH:MM:SSZ'."""
    if value is None:
        return None
    try:
        if isinstance(value, time.struct_time):
            dt = datetime(*value[:6], tzinfo=timezone.utc)
        elif isinstance(value, datetime):
            dt = value
        else:
            dt = dtparser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(iso: str) -> datetime:
    return dtparser.isoparse(iso)


def relative_hu(iso: str, now: datetime | None = None) -> str:
    now = now or now_utc()
    secs = int((now - parse_iso(iso)).total_seconds())
    if secs < 60:
        return "most"
    if secs < 3600:
        return f"{secs // 60} perce"
    if secs < 86400:
        return f"{secs // 3600} órája"
    return f"{secs // 86400} napja"
