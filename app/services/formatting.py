from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import get_settings

TZ = ZoneInfo(get_settings().timezone)


def money(v):
    d = Decimal(str(v))
    return f"{d:.2f}".rstrip("0").rstrip(".")


def active_applications(job) -> int:
    """Number of ACTIVE applications for a job.

    Works whether or not ``job.applications`` was eagerly loaded: if the
    relationship is not loaded we never touch it (that would trigger a lazy
    load inside async code and blow up with MissingGreenlet). Callers that
    need the exact count should pass ``filled`` explicitly or use the
    repository helper.
    """
    apps = job.__dict__.get("applications")
    if apps is None:
        return 0
    return len([a for a in apps if a.status.value == "ACTIVE"])


def job_text(job, filled: int | None = None, heading: str = "") -> str:
    if filled is None:
        filled = active_applications(job)
    start = job.start_at.astimezone(TZ)
    base = f"{heading + chr(10) if heading else ''}📦 <b>{job.title}</b>\n"
    if job.description:
        base += f"\n{job.description}\n"
    base += (
        f"\n💰 {money(job.hourly_rate)} €/час\n"
        f"⏱ {money(job.hours)} часов\n"
        f"💵 За смену: {money(Decimal(str(job.hourly_rate)) * Decimal(str(job.hours)))} €\n\n"
        f"📅 {start:%d.%m.%Y}\n"
        f"🕐 Приехать к {start:%H:%M}\n"
        f"📍 {job.address}\n\n"
        f"👥 Требуется: {job.required_workers}\n"
        f"👤 Уже записано: {filled}\n"
        f"🟢 Свободно: {max(job.required_workers - filled, 0)}"
    )
    return base
