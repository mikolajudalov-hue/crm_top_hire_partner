def create_app(testing=False):
    if testing:
        app.config["TESTING"] = True
        pass
    return app

from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for, session, g, abort, flash
from werkzeug.security import check_password_hash, generate_password_hash
from models import (
    db, User, Job, Candidate, Placement, BillingPeriod, PartnerDoc,
    CandidateComment, CandidateCommentSeen, CandidateLog, CandidateProfile,
    CandidateDoc, init_db, get_engine, News, NewsRead, RelaxHistory,
    JobHousingPhoto, RegistrationRequest, Notification, create_notification_for_users
)
from sqlalchemy import func
from auth_utils import login_required
from config import Config
import os

# =====================
#    APP INITIALIZATION
# =====================

app = Flask(__name__, instance_relative_config=False)

app.config.from_object(Config)

engine = get_engine()
init_db()
db.configure(bind=engine)

# =====================
#   CONTEXT PROCESSORS
# =====================

@app.context_processor
def inject_notifications():
    """Inject unread notifications count for the current user into all templates."""
    user = getattr(g, "user", None)
    unread = 0
    if user is not None:
        unread = (
            db.session.query(Notification)
            .filter_by(user_id=user.id, is_read=False)
            .count()
        )
    return {"unread_notifications": unread}


@app.context_processor
def inject_brand():
    lang = session.get("lang", "ru")
    return {"BRAND": Config.BRAND, "current_lang": lang}


# =====================
#      BEFORE REQUEST
# =====================

@app.before_request
def load_user_into_g():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db.session.get(User, uid)

    # Счётчики для шапки
    g.inbox_count = 0
    g.news_unread_count = 0

    # Флаги и данные профиля партнёра
    g.partner_profile_incomplete = False
    g.partner_profile_missing_fields = []

    if g.user and g.user.role in ("recruiter", "coordinator", "director"):
        g.inbox_count = (
            db.session.query(func.count(Candidate.id))
            .filter(Candidate.status == "Подан")
            .scalar()
        )

    if g.user:
        g.news_unread_count = (
            db.session.query(func.count(News.id))
            .outerjoin(
                NewsRead,
                (NewsRead.news_id == News.id) & (NewsRead.user_id == g.user.id)
            )
            .filter(News.is_published == True, NewsRead.id.is_(None))
            .scalar()
        )

        # Проверка заполненности профиля партнёра
        if g.user.role == "partner":
            required_fields = {
                "bank_account": "Реквизиты счета",
                "bank_name": "Банк",
                "company_name": "Название компании",
                "tax_id": "Tax ID / NIP",
                "address": "Адрес",
                "payout_note": "Комментарий по выплатам",
            }
            missing = []
            for field, label in required_fields.items():
                if not getattr(g.user, field, "").strip():
                    missing.append(label)
            g.partner_profile_missing_fields = missing
            g.partner_profile_incomplete = bool(missing)
# =====================
#         ROUTES
# =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")

        user = db.session.query(User).filter(
            User.email == email,
            User.is_active == True
        ).first()

        if not user or not check_password_hash(user.password_hash, password):
            return render_template("login.html", error="Неверные данные")

        session["uid"] = user.id
        return redirect(url_for("main.index"))

    return render_template("login.html")
@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("main.index"))

    # Список рекрутёров для выбора в форме
    recruiters = (
        db.session.query(User)
        .filter(User.role == "recruiter", User.is_active == True)
        .order_by(User.name.asc())
        .all()
    )

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        note = (request.form.get("note") or "").strip()
        partner_type = (request.form.get("partner_type") or "").strip()
        recruiter_id_raw = (request.form.get("assigned_recruiter_id") or "").strip()

        assigned_recruiter_id = None
        if recruiter_id_raw.isdigit():
            assigned_recruiter_id = int(recruiter_id_raw)

        # Простая валидация
        if not email:
            flash("Укажите email.", "danger")
            return render_template("register.html", recruiters=recruiters)

        if partner_type not in ("freelancer", "company"):
            flash("Выберите, вы работаете как фрилансер или как фирма.", "danger")
            return render_template("register.html", recruiters=recruiters)

        # Проверка: активный пользователь с таким email уже существует
        existing_user = (
            db.session.query(User)
            .filter(User.email == email, User.is_active == True)
            .first()
        )
        if existing_user:
            flash("Пользователь с таким email уже существует. Попробуйте войти или восстановить доступ.", "warning")
            return redirect(url_for("login"))

        # Проверка: уже есть новая заявка с таким email
        existing_req = (
            db.session.query(RegistrationRequest)
            .filter(RegistrationRequest.email == email, RegistrationRequest.status == "new")
            .first()
        )
        if existing_req:
            flash("Заявка с таким email уже подана. Мы свяжемся с вами в ближайшее время.", "info")
            return redirect(url_for("login"))

        req = RegistrationRequest(
            email=email,
            full_name=full_name,
            phone=phone,
            note=note,
            role="partner",
            partner_type=partner_type,
            status="new",
            assigned_recruiter_id=assigned_recruiter_id,
        )
        db.session.add(req)
        db.session.commit()

        # Уведомляем закреплённого рекрутёра о новой заявке
        if req.assigned_recruiter_id:
            create_notification_for_users(
                [req.assigned_recruiter_id],
                f"Новая заявка на регистрацию партнёра {req.full_name or req.email} закреплена за вами."
            )

        return redirect(url_for("register_thanks"))

    return render_template("register.html", recruiters=recruiters)


@app.route("/register/thanks")
def register_thanks():
    if g.user:
        return redirect(url_for("main.index"))
    return render_template("register_thanks.html")



@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if g.user is None:
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        current_password = (request.form.get("current_password") or "").strip()
        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if not current_password or not check_password_hash(g.user.password_hash, current_password):
            error = "Текущий пароль введён неверно."
        elif len(new_password) < 6:
            error = "Новый пароль должен быть не короче 6 символов."
        elif new_password != confirm_password:
            error = "Пароли не совпадают."
        else:
            g.user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("Пароль успешно обновлён.", "success")
            return redirect(url_for("main.index"))

    return render_template("change_password.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
#    BLUEPRINT REGISTRATION
# =========================

from blueprints.main import main_bp
from blueprints.jobs import jobs_bp
from blueprints.candidates import candidates_bp
from blueprints.finance import finance_bp
from blueprints.partner import partner_bp
from blueprints.admin import admin_bp
from blueprints.news import news_bp
from blueprints.notifications import notifications_bp
from blueprints.relax import relax_bp
from blueprints.training import training_bp


@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang not in ["ru", "uk"]:
        abort(404)
    session["lang"] = lang
    next_url = request.args.get("next") or url_for("main.index")
    return redirect(next_url)


app.register_blueprint(main_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(candidates_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(partner_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(news_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(relax_bp)
app.register_blueprint(training_bp)

# =====================
#      RUN SERVER
# =====================

PORT = int(os.environ.get("PORT", "8107"))


def create_app(testing=False):
    from models import db

    # Теперь не используем sqlite:///:memory: для тестирования,
    # предполагая, что тестовая база будет настроена через DATABASE_URL
    # или отдельный тестовый конфиг.
    pass
    app.config["TESTING"] = testing

    # ВАЖНО: ИНИЦИАЛИЗАЦИЯ БД ПОСЛЕ КОНФИГА
    db.init_app(app)

    return app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)



# Duplicate /register route removed
