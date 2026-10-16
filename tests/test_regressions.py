import pytest
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.models import (
    Application,
    ApplicationStatus,
    Base,
    Job,
    JobStatus,
    Role,
    User,
)
from app.database.repositories import (
    active_jobs,
    application_count,
    job_applications,
    upsert_user,
)
from app.services.formatting import job_text
from app.services.job_service import apply_to_job, cancel_application


class FakeTgUser:
    def __init__(self, uid, username="u", first_name="First", last_name="Last"):
        self.id = uid
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.language_code = "ru"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def make_job(session, required=1, status=JobStatus.ACTIVE, title="Job"):
    admin = await upsert_user(session, FakeTgUser(999), Role.ADMIN)
    await session.flush()
    job = Job(
        title=title,
        hourly_rate=10,
        hours=8,
        start_at=datetime.now(timezone.utc),
        address="addr",
        required_workers=required,
        status=status,
        created_by=admin.id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.commit()
    return job


@pytest.mark.asyncio
async def test_job_text_without_loaded_applications_does_not_crash(session):
    """Regression: admin:active used to lazy-load .applications -> MissingGreenlet."""
    job = await make_job(session, required=5)
    # job freshly fetched without selectinload
    from sqlalchemy import select

    fresh = (await session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    text = job_text(fresh)  # must not raise
    assert "Требуется: 5" in text
    assert "Уже записано: 0" in text


@pytest.mark.asyncio
async def test_active_jobs_eager_loads_applications(session):
    job = await make_job(session, required=2)
    user = await upsert_user(session, FakeTgUser(1))
    await session.commit()
    await apply_to_job(session, job.id, user, "Ivan Ivanov")

    jobs = await active_jobs(session)
    assert len(jobs) == 1
    # touching .applications must not perform IO
    assert len(list(jobs[0].applications)) == 1
    assert await application_count(session, job.id) == 1


@pytest.mark.asyncio
async def test_job_applications_returns_users(session):
    job = await make_job(session, required=3)
    u = await upsert_user(session, FakeTgUser(5, username="worker5"))
    await session.commit()
    await apply_to_job(session, job.id, u, "Petr Petrov")

    rows = await job_applications(session, job.id)
    assert len(rows) == 1
    app, user = rows[0]
    assert app.full_name == "Petr Petrov"
    assert user.username == "worker5"  # eagerly loaded, no lazy IO


@pytest.mark.asyncio
async def test_reapply_after_cancel_reactivates(session):
    """Regression: second apply after cancel used to violate uq_job_user."""
    job = await make_job(session, required=2)
    user = await upsert_user(session, FakeTgUser(7))
    await session.commit()

    app1, status1, _ = await apply_to_job(session, job.id, user, "A B")
    assert status1 == "ok"

    cancelled, _ = await cancel_application(session, job.id, user.id)
    assert cancelled is not None and cancelled.status == ApplicationStatus.CANCELLED

    app2, status2, _ = await apply_to_job(session, job.id, user, "A B")
    assert status2 == "ok", status2
    assert app2 is not None
    assert app2.id == app1.id  # same row reactivated
    assert await application_count(session, job.id) == 1


@pytest.mark.asyncio
async def test_cancel_reopens_filled_job(session):
    job = await make_job(session, required=1)
    user = await upsert_user(session, FakeTgUser(11))
    await session.commit()
    _, status, _ = await apply_to_job(session, job.id, user, "A B")
    assert status == "filled"
    assert job.status == JobStatus.FILLED

    await cancel_application(session, job.id, user.id)
    await session.refresh(job)
    assert job.status == JobStatus.ACTIVE


@pytest.mark.asyncio
async def test_filled_flag_uses_real_count(session):
    job = await make_job(session, required=2)
    u1 = await upsert_user(session, FakeTgUser(21))
    u2 = await upsert_user(session, FakeTgUser(22))
    await session.commit()
    await apply_to_job(session, job.id, u1, "A A")
    await apply_to_job(session, job.id, u2, "B B")

    from sqlalchemy import select

    fresh = (await session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    count = await application_count(session, job.id)
    assert count == 2
    text = job_text(fresh, count)
    assert "Уже записано: 2" in text
    assert "Свободно: 0" in text
