from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    Role,
    User,
)


async def upsert_user(session: AsyncSession, tg_user, role: Role = Role.WORKER) -> User:
    result = await session.execute(select(User).where(User.telegram_id == tg_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=tg_user.language_code,
            role=role,
            created_at=datetime.now(timezone.utc),
        )
        session.add(user)
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_name = tg_user.last_name
    await session.flush()
    return user


async def get_job(session: AsyncSession, job_id: int, lock: bool = False,
                  with_applications: bool = False) -> Job | None:
    stmt = select(Job).where(Job.id == job_id)
    if with_applications:
        stmt = stmt.options(selectinload(Job.applications))
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def active_jobs(session: AsyncSession):
    stmt = (
        select(Job)
        .options(selectinload(Job.applications))
        .where(Job.status == JobStatus.ACTIVE)
        .order_by(Job.start_at)
    )
    return (await session.execute(stmt)).scalars().all()


async def all_jobs(session: AsyncSession, status: JobStatus | None = None, limit: int | None = None):
    stmt = select(Job).options(selectinload(Job.applications)).order_by(Job.start_at)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    if limit is not None:
        stmt = stmt.limit(limit)
    return (await session.execute(stmt)).scalars().all()


async def application_count(session: AsyncSession, job_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count(Application.id)).where(
                    Application.job_id == job_id,
                    Application.status == ApplicationStatus.ACTIVE,
                )
            )
        ).scalar_one()
    )


async def user_application(session: AsyncSession, job_id: int, user_id: int):
    return (
        await session.execute(
            select(Application).where(
                Application.job_id == job_id, Application.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def job_applications(session: AsyncSession, job_id: int, active_only: bool = True):
    """Applications + users for a job, eagerly loaded (no lazy IO)."""
    stmt = (
        select(Application, User)
        .join(User, User.id == Application.user_id)
        .options(selectinload(Application.user))
        .where(Application.job_id == job_id)
        .order_by(Application.created_at)
    )
    if active_only:
        stmt = stmt.where(Application.status == ApplicationStatus.ACTIVE)
    return (await session.execute(stmt)).all()


async def create_application_locked(session: AsyncSession, job: Job, user: User,
                                    full_name: str) -> tuple[Application | None, str]:
    existing = await user_application(session, job.id, user.id)

    if existing and existing.status == ApplicationStatus.ACTIVE:
        return None, "already"

    if job.status != JobStatus.ACTIVE:
        return None, "closed"

    count = await application_count(session, job.id)
    if count >= job.required_workers:
        job.status = JobStatus.FILLED
        return None, "full"

    if existing is not None:
        # Re-activate a previously cancelled application instead of inserting a
        # new row: (job_id, user_id) is unique.
        existing.status = ApplicationStatus.ACTIVE
        existing.full_name = full_name.strip()
        existing.created_at = datetime.now(timezone.utc)
        app = existing
    else:
        app = Application(
            job_id=job.id,
            user_id=user.id,
            full_name=full_name.strip(),
            created_at=datetime.now(timezone.utc),
            status=ApplicationStatus.ACTIVE,
        )
        session.add(app)

    await session.flush()
    count += 1
    if count >= job.required_workers:
        job.status = JobStatus.FILLED
    return app, "filled" if count >= job.required_workers else "ok"
