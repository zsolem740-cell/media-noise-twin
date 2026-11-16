"""A napi kvóta visszaállásának ideje szolgáltatónként (zónaérzékenyen): Gemini éjfélkor Pacific Time-ban (America/Los_Angeles), Groq UTC éjfélkor.
A szabályt a felhasználó adta meg, hivatalos forrásból nem ellenőriztem: ezért a folytatás első kérése próba, és a szolgáltató saját jelzése is a naplóba kerül."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def as_utc(dt):
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def next_reset_utc(provider_cfg, now):
    tz = ZoneInfo(provider_cfg["quota_tz"])
    local = as_utc(now).astimezone(tz)
    nxt = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=tz)
    return nxt.astimezone(UTC)


def quota_day_key(provider_cfg, now):
    """A kvótanap azonosítója (a szolgáltató zónája szerinti dátum): ezen belül számoljuk a napi próbákat."""
    return as_utc(now).astimezone(ZoneInfo(provider_cfg["quota_tz"])).date().isoformat()


def resume_after_utc(provider_cfg, now, margin_min):
    return next_reset_utc(provider_cfg, now) + timedelta(minutes=margin_min)


def iso(dt):
    return as_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
