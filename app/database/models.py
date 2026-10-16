from datetime import datetime
from enum import Enum
from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Role(str, Enum):
    WORKER = "WORKER"
    ADMIN = "ADMIN"

class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"

class ApplicationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="role_enum"), default=Role.WORKER)
    language_code: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applications: Mapped[list["Application"]] = relationship(back_populates="user")

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2))
    hours: Mapped[float] = mapped_column(Numeric(6, 2))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    address: Mapped[str] = mapped_column(String(500))
    required_workers: Mapped[int] = mapped_column(Integer)
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus, name="job_status_enum"), default=JobStatus.DRAFT, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applications: Mapped[list["Application"]] = relationship(back_populates="job", cascade="all, delete-orphan")

class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "user_id", name="uq_job_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ApplicationStatus] = mapped_column(SAEnum(ApplicationStatus, name="application_status_enum"), default=ApplicationStatus.ACTIVE)
    job: Mapped[Job] = relationship(back_populates="applications")
    user: Mapped[User] = relationship(back_populates="applications")

class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("job_id", "kind", name="uq_job_reminder"),)
