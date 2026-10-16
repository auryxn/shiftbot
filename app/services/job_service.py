from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Application, ApplicationStatus, Job, JobStatus, User
from app.database.repositories import create_application_locked


async def apply_to_job(session: AsyncSession, job_id: int, user: User, full_name: str):
    async with session.begin():
        job = (
            await session.execute(select(Job).where(Job.id == job_id).with_for_update())
        ).scalar_one_or_none()
        if not job:
            return None, "missing", None
        app, status = await create_application_locked(session, job, user, full_name)
    return app, status, job


async def cancel_application(session: AsyncSession, job_id: int, user_id: int):
    async with session.begin():
        job = (
            await session.execute(select(Job).where(Job.id == job_id).with_for_update())
        ).scalar_one_or_none()
        app = (
            await session.execute(
                select(Application)
                .where(Application.job_id == job_id, Application.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not job or not app or app.status != ApplicationStatus.ACTIVE:
            return None, job
        app.status = ApplicationStatus.CANCELLED
        if job.status == JobStatus.FILLED:
            job.status = JobStatus.ACTIVE
    return app, job
