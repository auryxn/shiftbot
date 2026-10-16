import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    ReminderLog,
    User,
)
from app.services.formatting import TZ, job_text


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await bot.send_message(chat_id, text, **kwargs)
        except Exception:
            return None
    except (TelegramBadRequest, TelegramForbiddenError):
        return None
    except Exception:
        return None


async def broadcast_workers(session: AsyncSession, bot: Bot, text: str, reply_markup=None):
    users = (
        await session.execute(select(User.telegram_id).where(User.role == "WORKER"))
    ).scalars().all()
    for tg_id in users:
        await safe_send(bot, tg_id, text, reply_markup=reply_markup)
        await asyncio.sleep(0.05)


async def send_job_reminders(bot: Bot, session_factory):
    now = datetime.now(timezone.utc)
    windows = (
        ("24h", now + timedelta(hours=23, minutes=50), now + timedelta(hours=24, minutes=10)),
        ("2h", now + timedelta(hours=1, minutes=50), now + timedelta(hours=2, minutes=10)),
    )
    async with session_factory() as session:
        for kind, low, high in windows:
            jobs = (
                (
                    await session.execute(
                        select(Job).where(
                            Job.status.in_([JobStatus.ACTIVE, JobStatus.FILLED]),
                            Job.start_at >= low,
                            Job.start_at <= high,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for job in jobs:
                exists = (
                    await session.execute(
                        select(ReminderLog).where(
                            ReminderLog.job_id == job.id, ReminderLog.kind == kind
                        )
                    )
                ).scalar_one_or_none()
                if exists:
                    continue
                apps = (
                    await session.execute(
                        select(Application, User)
                        .join(User, User.id == Application.user_id)
                        .where(
                            Application.job_id == job.id,
                            Application.status == ApplicationStatus.ACTIVE,
                        )
                    )
                ).all()
                prefix = (
                    "⏰ Напоминание: работа уже завтра!"
                    if kind == "24h"
                    else "⏰ Работа начинается через 2 часа!"
                )
                for app, user in apps:
                    await safe_send(bot, user.telegram_id, prefix + "\n\n" + job_text(job, job.required_workers))
                session.add(ReminderLog(job_id=job.id, kind=kind, created_at=now))
        await session.commit()


async def close_past_jobs(session_factory):
    """Mark jobs whose start time has passed as COMPLETED and complete their applications."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        jobs = (
            (
                await session.execute(
                    select(Job).where(
                        Job.status.in_([JobStatus.ACTIVE, JobStatus.FILLED]),
                        Job.start_at < now - timedelta(hours=12),
                    )
                )
            )
            .scalars()
            .all()
        )
        for job in jobs:
            job.status = JobStatus.COMPLETED
            apps = (
                (
                    await session.execute(
                        select(Application).where(
                            Application.job_id == job.id,
                            Application.status == ApplicationStatus.ACTIVE,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for a in apps:
                a.status = ApplicationStatus.COMPLETED
        await session.commit()


async def reminder_loop(bot: Bot, session_factory):
    while True:
        try:
            await send_job_reminders(bot, session_factory)
            await close_past_jobs(session_factory)
        except Exception:
            pass
        await asyncio.sleep(60)
