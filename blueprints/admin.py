from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, g, abort, flash, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, text, case
from sqlalchemy.orm import aliased

from models import (
    db,
    User,
    Job,
    Candidate,
    Placement,
    BillingPeriod,
    PartnerDoc,
    CandidateComment,
    CandidateCommentSeen,
    CandidateLog,
    CandidateProfile,
    CandidateDoc,
    News,
    NewsRead,
    RelaxHistory,
    JobHousingPhoto,
    RegistrationRequest,
    Notification,
    create_notification_for_users,
)
from constants import PIPELINE
from auth_utils import login_required, roles_required

import os


admin_bp = Blueprint('admin', __name__)

@admin_bp.route("/admin/users")
@login_required
@roles_required("coordinator")
def admin_users():
    users = db.session.query(User).order_by(User.id.asc()).all()
    # Director filter: hide coordinators
    if g.user.role == "director":
        users = [u for u in users if u.role != "coordinator"]
    new_requests = (
        db.session.query(RegistrationRequest)
        .filter(RegistrationRequest.status == "new")
        .order_by(RegistrationRequest.created_at.desc())
        .all()
    )
    recruiters_map = {u.id: u.name for u in users if u.role == "recruiter"}
    return render_template("admin/users.html", users=users, new_requests=new_requests, recruiters_map=recruiters_map)



@admin_bp.route("/admin/registrations/<int:req_id>/approve", methods=["POST"])
@login_required
@roles_required("coordinator", "recruiter")
def registration_approve(req_id):
    req = db.session.get(RegistrationRequest, req_id)
    if not req:
        abort(404)
    redirect_endpoint = "admin.admin_users" if g.user.role in ("coordinator", "director") else "main.my_partners"
    if req.status != "new":
        flash("Эта заявка уже обработана.", "warning")
        return redirect(url_for(redirect_endpoint))

    # Рекрутёр может обрабатывать только заявки, закреплённые за ним
    if g.user.role == "recruiter" and req.assigned_recruiter_id != g.user.id:
        flash("Эта заявка не закреплена за вами.", "danger")
        return redirect(url_for("main.my_partners"))

    # Проверяем, нет ли уже пользователя с таким email
    existing_user = db.session.query(User).filter(User.email == req.email).first()
    if existing_user:
        flash("Пользователь с таким email уже существует. Заявка помечена как обработанная.", "warning")
        req.status = "approved"
        db.session.commit()
        return redirect(url_for("admin.admin_users"))

    temp_password = "0000"  # временный пароль, админ может потом сменить его в карточке пользователя
    user = User(
        name=req.full_name or req.email,
        email=req.email,
        password_hash=generate_password_hash(temp_password),
        role=req.role or "partner",
        partner_type=req.partner_type or "freelancer",
        is_active=True,
        assigned_recruiter_id=req.assigned_recruiter_id if req.role == "partner" else None,
        note=req.note or "",
    )
    db.session.add(user)
    req.status = "approved"
    db.session.commit()

    # Уведомим рекрутёра о создании партнёра, но пароль ему не показываем
    if user.assigned_recruiter_id:
        create_notification_for_users(
            [user.assigned_recruiter_id],
            f"Партнёр {user.name} ({user.email}) создан и закреплён за вами."
        )

    flash(f"Партнёр {user.email} создан.", "success")
    return redirect(url_for(redirect_endpoint))


@admin_bp.route("/admin/registrations/<int:req_id>/reject", methods=["POST"])
@login_required
@roles_required("coordinator", "recruiter")
def registration_reject(req_id):
    req = db.session.get(RegistrationRequest, req_id)
    if not req:
        abort(404)
    redirect_endpoint = "admin.admin_users" if g.user.role in ("coordinator", "director") else "main.my_partners"
    if req.status != "new":
        flash("Эта заявка уже обработана.", "warning")
        return redirect(url_for(redirect_endpoint))

    # Рекрутёр может отклонять только заявки, закреплённые за ним
    if g.user.role == "recruiter" and req.assigned_recruiter_id != g.user.id:
        flash("Эта заявка не закреплена за вами.", "danger")
        return redirect(url_for("main.my_partners"))

    req.status = "rejected"
    db.session.commit()
    flash("Заявка отклонена.", "info")
    return redirect(url_for(redirect_endpoint))


@admin_bp.route("/admin/users/new", methods=["GET","POST"])
@login_required
@roles_required("coordinator")
def admin_user_create():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = (request.form.get("role") or "recruiter").strip()
        partner_type = (request.form.get("partner_type") or "freelancer").strip()
        # Директор не может создавать админов и других директоров
        if g.user.role == "director" and role in ("coordinator", "director"):
            flash("Директор не может создавать админов и директоров.", "danger")
            return redirect(url_for("admin.admin_user_create"))
        is_active_val = request.form.get("is_active", "1")
        is_active = is_active_val == "1"
        partner_tier = (request.form.get("partner_tier") or "Bronze").strip()
        settlement_day_raw = (request.form.get("settlement_day") or "").strip()
        try:
            settlement_day = int(settlement_day_raw) if settlement_day_raw else 10
        except ValueError:
            settlement_day = 10
        if settlement_day < 1 or settlement_day > 28:
            settlement_day = 10

        assigned_recruiter_raw = (request.form.get("assigned_recruiter_id") or "").strip()
        try:
            assigned_recruiter_id = int(assigned_recruiter_raw) if assigned_recruiter_raw else None
        except ValueError:
            assigned_recruiter_id = None

        if not email or not password:
            flash("Email и пароль обязательны.", "danger")
            return redirect(url_for("admin.admin_user_create"))

        existing = db.session.query(User).filter(User.email == email).first()
        if existing:
            flash("Пользователь с таким email уже существует.", "danger")
            return redirect(url_for("admin.admin_user_create"))

        user = User(
            name=name or email,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            partner_type=partner_type if role == "partner" else "freelancer",
            is_active=is_active,
            note=partner_tier,
            settlement_day=settlement_day,
            assigned_recruiter_id=assigned_recruiter_id if role == "partner" else None,
        )
        db.session.add(user)
        db.session.commit()
        flash("Пользователь создан.", "success")
        return redirect(url_for("admin.admin_users"))

    roles = [
        ("coordinator", "Админ"),
        ("recruiter", "Рекрутер"),
        ("partner", "Партнёр"),
        ("finance", "Бухгалтер"),
    ]
    recruiters = (
        db.session.query(User)
        .filter(User.role == "recruiter", User.is_active == True)
        .order_by(User.name.asc())
        .all()
    )
    return render_template("admin/user_form.html", user=None, roles=roles, recruiters=recruiters)


@admin_bp.route("/admin/users/<int:user_id>/edit", methods=["GET","POST"])
@login_required
@roles_required("coordinator")
def admin_user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    # Директор не может редактировать админов и директоров
    if g.user.role == "director" and user.role in ("coordinator", "director"):
        flash("Директор не может редактировать админов и директоров.", "danger")
        return redirect(url_for("admin.admin_users"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = (request.form.get("role") or user.role).strip()
        partner_type = (request.form.get("partner_type") or (user.partner_type or "freelancer")).strip()
        # Директор не может назначать роль администратора или директора
        if g.user.role == "director" and role in ("coordinator", "director"):
            flash("Директор не может назначать роль администратора или директора.", "danger")
            return redirect(url_for("admin.admin_user_edit", user_id=user.id))
        is_active_val = request.form.get("is_active", "1")
        is_active = is_active_val == "1"
        partner_tier = (request.form.get("partner_tier") or (user.note or "Bronze")).strip()
        settlement_day_raw = (request.form.get("settlement_day") or "").strip()
        try:
            settlement_day = int(settlement_day_raw) if settlement_day_raw else (user.settlement_day or 10)
        except ValueError:
            settlement_day = user.settlement_day or 10
        if settlement_day < 1 or settlement_day > 28:
            settlement_day = user.settlement_day or 10

        assigned_recruiter_raw = (request.form.get("assigned_recruiter_id") or "").strip()
        try:
            assigned_recruiter_id = int(assigned_recruiter_raw) if assigned_recruiter_raw else None
        except ValueError:
            assigned_recruiter_id = None

        if not email:
            flash("Email обязателен.", "danger")
            return redirect(url_for("admin.admin_user_edit", user_id=user.id))

        existing = (
            db.session.query(User)
            .filter(User.email == email, User.id != user.id)
            .first()
        )
        if existing:
            flash("Пользователь с таким email уже существует.", "danger")
            return redirect(url_for("admin.admin_user_edit", user_id=user.id))

        user.name = name or email
        user.email = email
        user.role = role
        user.partner_type = partner_type if role == "partner" else (user.partner_type or "freelancer")
        user.is_active = is_active
        user.note = partner_tier
        user.settlement_day = settlement_day
        user.assigned_recruiter_id = assigned_recruiter_id if role == "partner" else None

        if password.strip():
            user.password_hash = generate_password_hash(password)

        db.session.commit()
        flash("Пользователь обновлён.", "success")
        return redirect(url_for("admin.admin_users"))

    roles = [
        ("coordinator", "Админ"),
        ("recruiter", "Рекрутер"),
        ("partner", "Партнёр"),
        ("finance", "Бухгалтер"),
        ("director", "Директор"),
    ]
    recruiters = (
        db.session.query(User)
        .filter(User.role == "recruiter", User.is_active == True)
        .order_by(User.name.asc())
        .all()
    )
    return render_template("admin/user_form.html", user=user, roles=roles, recruiters=recruiters)


@admin_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@roles_required("coordinator")
def admin_user_delete(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    # Директор не может удалять админов и директоров
    if g.user.role == "director" and user.role in ("coordinator", "director"):
        flash("Директор не может удалять админов и директоров.", "danger")
        return redirect(url_for("admin.admin_users"))
    if user.id == g.user.id:
        flash("Нельзя удалить самого себя.", "danger")
        return redirect(url_for("admin.admin_users"))

    has_candidates = db.session.query(Candidate.id).filter(
        Candidate.submitter_id == user.id
    ).limit(1).first()
    has_placements = db.session.query(Placement.id).filter(
        Placement.recruiter_id == user.id
    ).limit(1).first()

    if has_candidates or has_placements:
        flash(
            "Нельзя удалить пользователя, у которого есть кандидаты или закрытия. "
            "Вы можете сделать его неактивным.",
            "danger",
        )
        return redirect(url_for("admin.admin_users"))

    db.session.delete(user)
    db.session.commit()
    flash("Пользователь удалён.", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/admin/news")
@login_required
@roles_required("coordinator")
def admin_news():
    news_items = db.session.query(News).order_by(News.created_at.desc()).all()
    return render_template("admin/news_list.html", news_list=news_items)


@admin_bp.route("/admin/news/new", methods=["GET", "POST"])
@login_required
@roles_required("coordinator")
def admin_news_create():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        is_published = (request.form.get("is_published", "1") == "1")
        if not title:
            flash("Заголовок обязателен.", "danger")
            return render_template("admin/news_form.html", news=None)
        n = News(
            title=title,
            body=body,
            is_published=is_published,
            author_id=g.user.id,
        )
        db.session.add(n)
        db.session.commit()
        flash("Новость добавлена.", "success")
        return redirect(url_for("admin.admin_news"))
    return render_template("admin/news_form.html", news=None)


@admin_bp.route("/admin/news/<int:news_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required("coordinator")
def admin_news_edit(news_id):
    n = db.session.get(News, news_id)
    if not n:
        abort(404)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        is_published = (request.form.get("is_published", "1") == "1")
        if not title:
            flash("Заголовок обязателен.", "danger")
            return render_template("admin/news_form.html", news=n)
        n.title = title
        n.body = body
        n.is_published = is_published
        db.session.commit()
        flash("Новость обновлена.", "success")
        return redirect(url_for("admin.admin_news"))
    return render_template("admin/news_form.html", news=n)


@admin_bp.route("/admin/news/<int:news_id>/delete", methods=["POST"])
@login_required
@roles_required("coordinator")
def admin_news_delete(news_id):
    n = db.session.get(News, news_id)
    if not n:
        abort(404)
    db.session.query(NewsRead).filter(NewsRead.news_id == news_id).delete()
    db.session.delete(n)
    db.session.commit()
    flash("Новость удалена.", "success")
    return redirect(url_for("admin.admin_news"))
