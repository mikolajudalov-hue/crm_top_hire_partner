from datetime import datetime
import os
from sqlalchemy import (
    String, Float, Text, Boolean, DateTime, ForeignKey,
    Integer, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, scoped_session

DB_PATH = os.environ.get("DB_PATH", "database.db")


class Base(DeclarativeBase):
    pass


# =====================
#       USERS
# =====================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    role: Mapped[str] = mapped_column(String(32))  # coordinator | recruiter | partner
    # Тип партнёра: freelancer / company (используется только для партнёров)
    partner_type: Mapped[str] = mapped_column(String(32), default="freelancer")

    # Назначенный рекрутёр для партнёра (кто подтверждает месяц)
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




# =====================
#   REGISTRATION REQUESTS
# =====================

class RegistrationRequest(Base):
    __tablename__ = "registration_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(32), default="partner")
    # Тип будущего партнёра: freelancer / company
    partner_type: Mapped[str] = mapped_column(String(32), default="freelancer")
    status: Mapped[str] = mapped_column(String(32), default="new")
    # Назначенный рекрутёр, к которому будет привязана эта заявка
    assigned_recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    requested_password: Mapped[str] = mapped_column(String(255), default="")


# =====================
#         JOBS
# =====================

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

    # Сколько людей нужно по вакансии
    needed_male: Mapped[int] = mapped_column(Integer, default=0)
    needed_female: Mapped[int] = mapped_column(Integer, default=0)
    allow_family_couples: Mapped[bool] = mapped_column(Boolean, default=True)

    partner_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)
    # DEPRECATED: комиссия рекрутёру больше не используется
    recruiter_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)

    promo_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    promo_label: Mapped[str] = mapped_column(String(255), default="")

    male_bonus_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    male_bonus_percent: Mapped[float] = mapped_column(Float, default=0.0)

    thumbnail_image: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def partner_fee_effective(self) -> float:
        base = self.partner_fee_amount or 0.0
        mult = self.promo_multiplier or 1.0
        return round(base * mult, 2)
# =====================
#      TRAINING / LEARNING
# =====================

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
    section_id: Mapped[int] = mapped_column(ForeignKey("training_sections.id"), nullable=False, index=True)
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
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[int] = mapped_column(Integer, default=5)
    level: Mapped[str] = mapped_column(String(64), default="")
    answers_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)





class TrainingLessonProgress(Base):
    __tablename__ = "training_lesson_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("training_lessons.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#      JOB HOUSING PHOTOS
# =====================

class JobHousingPhoto(Base):
    __tablename__ = "job_housing_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#       CANDIDATES
# =====================

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

    # Причина отказа / невыхода (последняя зафиксированная)
    status_reason_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_status_reasons.id"), nullable=True)
    status_reason_comment: Mapped[str] = mapped_column(Text, default="")

    partner_fee_offer: Mapped[float] = mapped_column(Float, default=0.0)
    # DEPRECATED: комиссия рекрутёру больше не используется
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
    planned_arrival: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    citizenship: Mapped[str] = mapped_column(String(200), default="")


# =====================
#      PLACEMENT
# =====================

class Placement(Base):
    __tablename__ = "placements"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    start_date: Mapped[str] = mapped_column(String(10))

    partner_commission: Mapped[float] = mapped_column(Float, default=0.0)
    # DEPRECATED: комиссия рекрутёру больше не используется
    recruiter_commission: Mapped[float] = mapped_column(Float, default=0.0)

    recruiter_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    recruiter_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    recruiter_confirmed_by_id: Mapped[int | None] = mapped_column(Integer, default=None)

    status: Mapped[str] = mapped_column(String(32), default="Вышел на работу")

    partner_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_paid_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    partner_payment_file: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#   CANDIDATE DOCS
# =====================

class CandidateDoc(Base):
    __tablename__ = "candidate_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))

    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#          NEWS
# =====================

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


# =====================
#     RELAX HISTORY
# =====================

class RelaxHistory(Base):
    __tablename__ = "relax_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#   CANDIDATE LOGS / COMMENTS
# =====================

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


# =====================
#   BILLING PERIODS
# =====================



class CandidateStatusReason(Base):
    __tablename__ = "candidate_status_reasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title_ru: Mapped[str] = mapped_column(String(255))
    title_uk: Mapped[str] = mapped_column(String(255), default="")
    applies_to_status: Mapped[str] = mapped_column(String(64), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BillingPeriod(Base):
    __tablename__ = "billing_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))

    placements_count: Mapped[int] = mapped_column(default=0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)

    invoice_filename: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#      PARTNER DOCS
# =====================

class PartnerDoc(Base):
    __tablename__ = "partner_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(400))
    label: Mapped[str] = mapped_column(String(255), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# =====================
#       ENGINE / SESSION / DB
# =====================

def get_engine(path=None):
    if path is None:
        path = DB_PATH
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )


engine = get_engine()
Session = scoped_session(sessionmaker(bind=engine))


def init_db():
    # Создаём таблицы, если их ещё нет
    Base.metadata.create_all(engine)

    # Лёгкая миграция для SQLite: добавляем недостающие колонки
    try:
        with engine.begin() as conn:
            # users.partner_type
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info('users')"))}
            if "partner_type" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN partner_type VARCHAR(32) DEFAULT 'freelancer'"))

            # registration_requests.partner_type
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info('registration_requests')"))}
            if "partner_type" not in cols:
                conn.execute(text("ALTER TABLE registration_requests ADD COLUMN partner_type VARCHAR(32) DEFAULT 'freelancer'"))

            # jobs.needed_male / needed_female / allow_family_couples
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info('jobs')"))}
            if "needed_male" not in cols:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN needed_male INTEGER DEFAULT 0"))
            if "needed_female" not in cols:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN needed_female INTEGER DEFAULT 0"))
            if "allow_family_couples" not in cols:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN allow_family_couples BOOLEAN DEFAULT 1"))

            # training_lessons.image_url
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info('training_lessons')"))}
            if "image_url" not in cols:
                conn.execute(text("ALTER TABLE training_lessons ADD COLUMN image_url VARCHAR(255) DEFAULT ''"))

            # candidates.status_reason_*
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info('candidates')"))}
            if "status_reason_id" not in cols:
                conn.execute(text("ALTER TABLE candidates ADD COLUMN status_reason_id INTEGER"))
            if "status_reason_comment" not in cols:
                conn.execute(text("ALTER TABLE candidates ADD COLUMN status_reason_comment TEXT DEFAULT ''"))

            # billing_periods.status
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info('billing_periods')"))}
            if "status" not in cols:
                conn.execute(text("ALTER TABLE billing_periods ADD COLUMN status VARCHAR(32) DEFAULT 'draft'"))
    except Exception:
        # На бою лучше логировать, здесь просто не падаем
        pass

    # Базовое наполнение обучения: если ещё нет разделов, пробуем загрузить их из training_seed.json
    try:
        from sqlalchemy.orm import Session
        from pathlib import Path
        import json

        with Session(engine) as session:
            if not session.query(TrainingSection).first():
                seed_path = Path(__file__).with_name("training_seed.json")
                if seed_path.exists():
                    data = json.loads(seed_path.read_text(encoding="utf-8"))

                    # Разделы и уроки
                    for idx, s in enumerate(data.get("sections", []), start=1):
                        sec = TrainingSection(
                            slug=s.get("slug") or f"section-{idx}",
                            title=s.get("title") or f"Раздел {idx}",
                            description=s.get("description") or "",
                            sort_order=s.get("sort_order") or idx * 10,
                        )
                        session.add(sec)
                        session.flush()

                        lessons = s.get("lessons", []) or []
                        for jdx, lesson in enumerate(lessons, start=1):
                            l = TrainingLesson(
                                section_id=sec.id,
                                slug=lesson.get("slug") or f"lesson-{sec.id}-{jdx}",
                                title=lesson.get("title") or f"Урок {jdx}",
                                content=lesson.get("content") or "",
                                image_url=lesson.get("image_url") or "",
                                estimated_minutes=lesson.get("estimated_minutes") or 10,
                                sort_order=lesson.get("sort_order") or jdx * 10,
                            )
                            session.add(l)

                    # Вопросы для теста «Хороший ли ты партнёр»
                    for qidx, q in enumerate(data.get("partner_quiz_questions", []), start=1):
                        qq = TrainingPartnerQuizQuestion(
                            text=q.get("text") or "",
                            dimension=q.get("dimension") or "general",
                            sort_order=q.get("sort_order") or qidx * 10,
                        )
                        session.add(qq)

                    
                    # Статусы причин по кандидатам: если ещё нет, создаём базовый набор
                    if not session.query(CandidateStatusReason).first():
                        base_reasons = [
                            dict(code="no_show_first_day", title_ru="Не вышел в первый день", applies_to_status="Не вышел", sort_order=10),
                            dict(code="no_show_after_training", title_ru="Не вышел после обучения / инструктажа", applies_to_status="Не вышел", sort_order=20),
                            dict(code="refused_conditions", title_ru="Отказался из-за условий работы", applies_to_status="Не вышел", sort_order=30),
                            dict(code="refused_salary", title_ru="Отказался из-за зарплаты", applies_to_status="Не вышел", sort_order=40),
                            dict(code="personal_reasons", title_ru="Личные обстоятельства (семья, здоровье)", applies_to_status="Не вышел", sort_order=50),
                            dict(code="moved_to_another_job", title_ru="Ушёл на другую работу", applies_to_status="Не отработал", sort_order=60),
                            dict(code="low_performance", title_ru="Низкая производительность / жалобы клиента", applies_to_status="Не отработал", sort_order=70),
                            dict(code="discipline_issues", title_ru="Проблемы с дисциплиной (опоздания, прогулы)", applies_to_status="Не отработал", sort_order=80),
                            dict(code="housing_issues", title_ru="Проблемы с жильём (условия, соседи)", applies_to_status="Не вышел", sort_order=90),
                            dict(code="unknown_reason", title_ru="Причина не уточнена", applies_to_status="", sort_order=100),
                        ]
                        for idx, r in enumerate(base_reasons, start=1):
                            session.add(
                                CandidateStatusReason(
                                    code=r["code"],
                                    title_ru=r["title_ru"],
                                    title_uk="",
                                    applies_to_status=r.get("applies_to_status", ""),
                                    sort_order=r.get("sort_order", idx * 10),
                                    is_active=True,
                                )
                            )

                    session.commit()

    except Exception:
        # Если что-то пойдёт не так при загрузке обучающего контента — не ломаем приложение
        pass

class _DBProxy:
    def __init__(self, scoped):
        self._scoped = scoped
        self.session = scoped

    def __getattr__(self, name):
        return getattr(self._scoped, name)


db = _DBProxy(Session)


from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime, ForeignKey

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


def create_notification_for_users(user_ids, message: str) -> None:
    """Создать уведомление для списка пользователей (без коммита).

    user_ids: итерируемый список ID пользователей.
    message: текст уведомления.
    """
    # Импорт здесь, чтобы избежать циклических импортов при использовании в других местах
    unique_ids = set()
    for uid in user_ids:
        if uid:
            unique_ids.add(uid)
    for uid in unique_ids:
        note = Notification(user_id=uid, message=message)
        db.session.add(note)
