"""Utilità date/ore (UTC) condivise dall'orchestratore. Compatibili con Python 3.10+."""

from datetime import datetime, timezone


def parse_iso(s: str) -> datetime:
    """ISO-8601 (anche con suffisso Z) → datetime UTC aware."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def giorni_calendario(da: datetime, a: datetime) -> int:
    """Giorni di calendario (UTC) tra due istanti: un invito delle 15:00 di lunedì è a +2
    il mercoledì a qualsiasi ora, così un job giornaliero non slitta di un giorno."""
    return (a.astimezone(timezone.utc).date() - da.astimezone(timezone.utc).date()).days
