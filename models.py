from datetime import datetime
import os
from sqlalchemy import String, Float, Text, Boolean, DateTime, ForeignKey, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, scoped_session

DB_PATH = os.environ.get("DB_PATH", "database.db")

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))  # coordinator|recruiter|partner
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Новое: заметки по партнёру / рекрутёру — «даёт только грузинов», «надёжный», и т.п.
    note: Mapped[str] = mapped_column(Text, default="")
    # Новое: блокировка отправки кандидатов от этого пользователя (для партнёров с пометкой «не брать»)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    bank_account: Mapped[str] = mapped_column(String(255), default="")
    bank_name: Mapped[str] = mapped_column(String(255), default="")
    company_name: Mapped[str] = mapped_column(String(255), default="")
    tax_id: Mapped[str] = mapped_column(String(100), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    payout_note: Mapped[str] = mapped_column(Text, default="")

    # Расчётный день месяца для выплат партнёру (1–28)
    settlement_day: Mapped[int] = mapped_column(Integer, default=10)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    short_description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    priority: Mapped[str] = mapped_column(String(32), default="normal")  # urgent|normal|low
    # Требования по кандидату
    gender_preference: Mapped[str] = mapped_column(String(32), default="")  # m/f/any, хранится как текст
    age_to: Mapped[int] = mapped_column(Integer, default=0)  # 0 = без ограничения
    # Вознаграждение
    partner_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)
    recruiter_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)
    promo_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    promo_label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def partner_fee_effective(self) -> float:
        """Комиссия партнёру с учётом текущего бустера."""
        base = self.partner_fee_amount or 0.0
        mult = self.promo_multiplier or 1.0
        return round(base * mult, 2)

class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    submitter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    cv_url: Mapped[str] = mapped_column(String(400), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="Подан")
    partner_fee_offer: Mapped[float] = mapped_column(Float, default=0.0)
    recruiter_fee_offer: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)
    has_driver_license: Mapped[bool] = mapped_column(Boolean, default=False)
    work_experience: Mapped[str] = mapped_column(Text, default="")
    age: Mapped[int] = mapped_column(nullable=True)
    has_work_shoes: Mapped[bool] = mapped_column(Boolean, default=False)
    planned_arrival: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    citizenship: Mapped[str] = mapped_column(String(200), default="")

class Placement(Base):
    __tablename__ = "placements"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    partner_commission: Mapped[float] = mapped_column(Float, default=0.0)
    recruiter_commission: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="Вышел на работу")

    partner_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_paid_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    partner_payment_file: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



class CandidateDoc(Base):
    __tablename__ = "candidate_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)




class News(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NewsRead(Base):
    __tablename__ = "news_read"
    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class CandidateComment(Base):
    __tablename__ = "candidate_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CandidateCommentSeen(Base):
    __tablename__ = "candidate_comment_seen"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class CandidateLog(Base):
    __tablename__ = "candidate_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



class BillingPeriod(Base):
    __tablename__ = "billing_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    end_date: Mapped[str] = mapped_column(String(10))    # YYYY-MM-DD
    placements_count: Mapped[int] = mapped_column(default=0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    invoice_filename: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PartnerDoc(Base):
    __tablename__ = "partner_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

def get_engine():
    return create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

Session = scoped_session(sessionmaker())

def init_db(engine):
    Base.metadata.create_all(engine)

class _DBProxy:
    def __init__(self, scoped):
        self._scoped = scoped
        self.session = scoped
    def __getattr__(self, name):
        return getattr(self._scoped, name)

db = _DBProxy(Session)