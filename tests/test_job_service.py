import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database.models import Base, User, Job, Role, JobStatus
from app.services.job_service import apply_to_job

@pytest.mark.asyncio
async def test_last_place_is_only_one():
    engine=create_async_engine('sqlite+aiosqlite:///:memory:',future=True)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    Session=async_sessionmaker(engine,expire_on_commit=False)
    async with Session() as s:
        u1=User(telegram_id=1,role=Role.WORKER,created_at=datetime.now(timezone.utc)); u2=User(telegram_id=2,role=Role.WORKER,created_at=datetime.now(timezone.utc)); s.add_all([u1,u2]); await s.flush()
        j=Job(title='x',hourly_rate=10,hours=8,start_at=datetime.now(timezone.utc),address='x',required_workers=1,status=JobStatus.ACTIVE,created_by=1,created_at=datetime.now(timezone.utc)); s.add(j); await s.commit()
        a,status,j=await apply_to_job(s,j.id,u1,'A A'); assert a is not None and status=='filled'
    await engine.dispose()
