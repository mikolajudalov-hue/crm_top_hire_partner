from datetime import datetime
import os
from sqlalchemy import (
    String, Float, Text, Boolean, DateTime, ForeignKey,
    Integer, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, scoped_session

# ------------------------------------------------------
# BASE CLASS
# ------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ------------------------------------------------------
# USERS
# ------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    role: Mapped[str] = mapped_column(String(32))
    partner_type: Mapped[str] = mapped_column(String(32), default="freelancer")

    assigned_recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    note: Mapped[str] = mapped_column(Text, default="")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_seen: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_times_shown: Mapped[int] = mapped_column(Integer, default=0)

    bank_account: Mapped[str] = mapped_column(String(255), default="")
    bank_name: Mapped[str] = mapped_column(String(255), default="")
    company_name: Mapped[str] = mapped_column(String(255), default="")
    tax_id: Mapped[str] = mapped_column(String(100), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    payout_note: Mapped[str] = mapped_column(Text, default="")

    settlement_day: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# REGISTRATION REQUESTS
# ------------------------------------------------------

class RegistrationRequest(Base):
    __tablename__ = "registration_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(32), default="partner")
    partner_type: Mapped[str] = mapped_column(String(32), default="freelancer")
    status: Mapped[str] = mapped_column(String(32), default="new")
    assigned_recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    requested_password: Mapped[str] = mapped_column(String(255), default="")


# ------------------------------------------------------
# JOBS
# ------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    short_description: Mapped[str] = mapped_column(String(255), default="")

    status: Mapped[str] = mapped_column(String(32), default="active")
    priority: Mapped[str] = mapped_column(String(32), default="normal")

    gender_preference: Mapped[str] = mapped_column(String(32), default="")
    age_to: Mapped[int] = mapped_column(Integer, default=0)

    needed_male: Mapped[int] = mapped_column(Integer, default=0)
    needed_female: Mapped[int] = mapped_column(Integer, default=0)
    allow_family_couples: Mapped[bool] = mapped_column(Boolean, default=True)

    partner_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)
    recruiter_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)

    promo_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    promo_label: Mapped[str] = mapped_column(String(255), default="")

    male_bonus_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    male_bonus_percent: Mapped[float] = mapped_column(Float, default=0.0)

    thumbnail_image: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# TRAINING
# ------------------------------------------------------

class TrainingSection(Base):
    __tablename__ = "training_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingLesson(Base):
    __tablename__ = "training_lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("training_sections.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(255), default="")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingPartnerQuizQuestion(Base):
    __tablename__ = "training_partner_quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    dimension: Mapped[str] = mapped_column(String(64), default="general")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingPartnerQuizResult(Base):
    __tablename__ = "training_partner_quiz_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[int] = mapped_column(Integer, default=5)
    level: Mapped[str] = mapped_column(String(64), default="")
    answers_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TrainingLessonProgress(Base):
    __tablename__ = "training_lesson_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("training_lessons.id"))
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# JOB HOUSING PHOTOS
# ------------------------------------------------------

class JobHousingPhoto(Base):
    __tablename__ = "job_housing_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# CANDIDATES
# ------------------------------------------------------

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

    status_reason_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_status_reasons.id"))
    status_reason_comment: Mapped[str] = mapped_column(Text, default="")

    partner_fee_offer: Mapped[float] = mapped_column(Float, default=0.0)
    recruiter_fee_offer: Mapped[float] = mapped_column(Float, default=0.0)

    gender: Mapped[str] = mapped_column(String(16), default="")
    partner_reward: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)

    has_driver_license: Mapped[bool] = mapped_column(Boolean, default=False)
    work_experience: Mapped[str] = mapped_column(Text, default="")
    age: Mapped[int] = mapped_column(nullable=True)
    has_work_shoes: Mapped[bool] = mapped_column(Boolean, default=False)
    planned_arrival: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    citizenship: Mapped[str] = mapped_column(String(200), default="")


# ------------------------------------------------------
# PLACEMENTS
# ------------------------------------------------------

class Placement(Base):
    __tablename__ = "placements"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    start_date: Mapped[str] = mapped_column(String(10))

    partner_commission: Mapped[float] = mapped_column(Float, default=0.0)
    recruiter_commission: Mapped[float] = mapped_column(Float, default=0.0)

    recruiter_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    recruiter_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recruiter_confirmed_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="Вышел на работу")

    partner_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    partner_payment_file: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# DOCS
# ------------------------------------------------------

class CandidateDoc(Base):
    __tablename__ = "candidate_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# NEWS
# ------------------------------------------------------

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


# ------------------------------------------------------
# RELAX HISTORY / LOGS
# ------------------------------------------------------

class RelaxHistory(Base):
    __tablename__ = "relax_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


# ------------------------------------------------------
# STATUS REASONS
# ------------------------------------------------------

class CandidateStatusReason(Base):
    __tablename__ = "candidate_status_reasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title_ru: Mapped[str] = mapped_column(String(255))
    title_uk: Mapped[str] = mapped_column(String(255), default="")
    applies_to_status: Mapped[str] = mapped_column(String(64), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ------------------------------------------------------
# BILLING PERIODS
# ------------------------------------------------------

class BillingPeriod(Base):
    __tablename__ = "billing_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    placements_count: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    invoice_filename: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# PARTNER DOCS
# ------------------------------------------------------

class PartnerDoc(Base):
    __tablename__ = "partner_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------
# ENGINE / SESSION
# ------------------------------------------------------

DB_URL = os.environ.get("DATABASE_URL")

def get_engine():
    if DB_URL:
        return create_engine(DB_URL, pool_pre_ping=True)
    else:
        return create_engine("sqlite:///local.db", connect_args={"check_same_thread": False})


engine = get_engine()
Session = scoped_session(sessionmaker(bind=engine))


# ------------------------------------------------------
# INIT DB (CREATE TABLES + SEED)
# ------------------------------------------------------

def init_db():
    Base.metadata.create_all(engine)

    try:
        from sqlalchemy.orm import Session as Sess
        from pathlib import Path
        import json

        with Sess(engine) as session:
            if not session.query(TrainingSection).first():
                seed_file = Path(__file__).with_name("training_seed.json")
                if seed_file.exists():
                    data = json.loads(seed_file.read_text(encoding="utf-8"))

                    # Sections
                    for idx, sec in enumerate(data.get("sections", []), start=1):
                        section = TrainingSection(
                            slug=sec.get("slug") or f"section-{idx}",
                            title=sec.get("title") or f"Раздел {idx}",
                            description=sec.get("description") or "",
                            sort_order=sec.get("sort_order") or idx * 10,
                        )
                        session.add(section)
                        session.flush()

                        for jdx, lesson in enumerate(sec.get("lessons", []), start=1):
                            session.add(
                                TrainingLesson(
                                    section_id=section.id,
                                    slug=lesson.get("slug") or f"lesson-{section.id}-{jdx}",
                                    title=lesson.get("title") or f"Урок {jdx}",
                                    content=lesson.get("content") or "",
                                    image_url=lesson.get("image_url") or "",
                                    estimated_minutes=lesson.get("estimated_minutes") or 10,
                                    sort_order=lesson.get("sort_order") or jdx * 10,
                                )
                            )

                    # Status reasons
                    if not session.query(CandidateStatusReason).first():
                        reasons = [
                            dict(code="no_show_first_day", title_ru="Не вышел в первый день", applies_to_status="Не вышел", sort_order=10),
                            dict(code="no_show_after_training", title_ru="Не вышел после обучения / инструктажа", applies_to_status="Не вышел", sort_order=20),
                            dict(code="refused_conditions", title_ru="Отказ из-за условий", applies_to_status="Не вышел", sort_order=30),
                            dict(code="refused_salary", title_ru="Отказ из-за зарплаты", applies_to_status="Не вышел", sort_order=40),
                            dict(code="personal_reasons", title_ru="Личные причины", applies_to_status="Не вышел", sort_order=50),
                            dict(code="moved_to_another_job", title_ru="Ушёл на другую работу", applies_to_status="Не отработал", sort_order=60),
                            dict(code="low_performance", title_ru="Низкая продуктивность", applies_to_status="Не отработал", sort_order=70),
                            dict(code="discipline_issues", title_ru="Дисциплинарные проблемы", applies_to_status="Не отработал", sort_order=80),
                            dict(code="housing_issues", title_ru="Проблемы с жильём", applies_to_status="Не вышел", sort_order=90),
                            dict(code="unknown_reason", title_ru="Не указано", applies_to_status="", sort_order=100),
                        ]
                        for r in reasons:
                            session.add(CandidateStatusReason(**r))

                    session.commit()

    except Exception as e:
        print("INIT DB ERROR:", e)


# ------------------------------------------------------
# DB PROXY (как раньше)
# ------------------------------------------------------

class _DBProxy:
    def __init__(self, scoped):
        self._scoped = scoped
        self.session = scoped

    def __getattr__(self, name):
        return getattr(self._scoped, name)


db = _DBProxy(Session)
