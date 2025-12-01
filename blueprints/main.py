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
    Notification,
    create_notification_for_users,
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
)
from constants import PIPELINE
from auth_utils import login_required, roles_required

import os


main_bp = Blueprint('main', __name__)

@main_bp.route("/")
@login_required
def index():
    u = g.user
    ym = date.today().strftime("%Y-%m")
    if u.role == "partner":
        # Показываем партнёру только несколько верхних вакансий на дашборде,
        # чтобы блок "Мои подачи" всегда был под рукой.
        jobs = (db.session.query(Job)
                .filter(Job.status=="active")
                .order_by(
                    case((Job.priority=="top", 0),
                         (Job.priority=="urgent", 1),
                         (Job.priority=="normal", 2),
                         else_=3),
                    Job.created_at.desc()
                )
                .limit(4)
                .all())

        # Фильтры для блока «Мои подачи»
        sub_job_id = request.args.get("job_id", type=int)
        sub_status = request.args.get("status")
        sub_q = (request.args.get("q") or "").strip()

        q_sub = (db.session.query(Candidate, case((Job.status=="active", Job.title), else_=None).label("job_title"))
                 .join(Job, Candidate.job_id==Job.id)
                 .filter(Candidate.submitter_id==u.id,
                         Candidate.status != "Удалён"))
        if sub_job_id:
            q_sub = q_sub.filter(Candidate.job_id==sub_job_id)
        if sub_status:
            q_sub = q_sub.filter(Candidate.status==sub_status)
        if sub_q:
            like_val = f"%{sub_q}%"
            q_sub = q_sub.filter(Candidate.full_name.ilike(like_val))
        submissions = q_sub.order_by(Candidate.created_at.desc()).limit(200).all()

        # Метрики: подачи/старты/заработок
        my_submissions = db.session.query(func.count(Candidate.id)).filter(
            Candidate.submitter_id==u.id,
            func.to_char(Candidate.created_at, 'YYYY-MM')==ym,
            Candidate.status != "Удалён").scalar() or 0

        my_starts = (db.session.query(func.count(Placement.id))
                     .join(Candidate, Candidate.id==Placement.candidate_id)
                     .filter(Candidate.submitter_id==u.id,
                             func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM')==ym).scalar() or 0)

        # Начислено за месяц
        my_month_accrued = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                             .join(Candidate, Candidate.id==Placement.candidate_id)
                             .filter(Candidate.submitter_id==u.id,
                                     func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM')==ym).scalar() or 0.0)

        # Выплачено за месяц
        my_month_paid = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                          .join(Candidate, Candidate.id==Placement.candidate_id)
                          .filter(Candidate.submitter_id==u.id,
                                  Placement.partner_paid == True,
                                  Placement.partner_paid_at.is_not(None),
                                  func.to_char(Placement.partner_paid_at, 'YYYY-MM')==ym).scalar() or 0.0)

        # Общий баланс: начислено минус выплачено (за всё время)
        total_accrued = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                          .join(Candidate, Candidate.id==Placement.candidate_id)
                          .filter(Candidate.submitter_id==u.id).scalar() or 0.0)
        total_paid = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                       .join(Candidate, Candidate.id==Placement.candidate_id)
                       .filter(Candidate.submitter_id==u.id,
                               Placement.partner_paid == True).scalar() or 0.0)
        my_balance = total_accrued - total_paid

        # Потенциальный заработок: кандидаты, которые вышли на работу < 30 дней назад и ещё не оплачены
        potential_sum = 0.0
        today = date.today()
        potential_q = (db.session.query(Placement)
                       .join(Candidate, Candidate.id==Placement.candidate_id)
                       .filter(Candidate.submitter_id==u.id,
                               Candidate.status=="Вышел на работу"))
        for pl in potential_q.all():
            if pl.partner_paid:
                continue
            try:
                sd = datetime.strptime(pl.start_date, "%Y-%m-%d").date()
            except Exception:
                continue
            days = (today - sd).days
            if 0 <= days < 30:
                potential_sum += pl.partner_commission

        partner_note = u.note or ""
        return render_template(
            "dash_partner.html",
            jobs=jobs,
            submissions=submissions,
            partner_note=partner_note,
            pipeline=PIPELINE,
            current_filters={"job_id": sub_job_id, "status": sub_status, "q": sub_q},
            kpi={
                "my_submissions": my_submissions,
                "my_starts": my_starts,
                "my_partner_sum": round(my_month_accrued, 2),
                "my_partner_paid": round(my_month_paid, 2),
                "my_partner_balance": round(my_balance, 2),
                "my_total_earned": round(total_paid, 2),
                "my_potential_next": round(potential_sum, 2),
            },
        )
    else:
        submissions = (db.session.query(Candidate,
                        case((Job.status=="active", Job.title), else_=None).label("job_title"),
                        User.name.label("submitter_name"),
                        User.note.label("submitter_note"))
                       .join(Job, Candidate.job_id==Job.id)
                       .join(User, User.id==Candidate.submitter_id)
                       .order_by(Candidate.created_at.desc()).limit(50).all())
        placements = (db.session.query(Placement,
                        Candidate.full_name.label("cand_name"),
                        Job.title.label("job_title"),
                        User.name.label("recruiter_name"),
                        db.session.query(User.name).filter(User.id==Candidate.submitter_id).correlate(Candidate).scalar_subquery().label("partner_name"))
                       .join(Candidate, Candidate.id==Placement.candidate_id)
                       .join(Job, Job.id==Placement.job_id)
                       .join(User, User.id==Placement.recruiter_id)
                       .order_by(Placement.created_at.desc()).limit(50).all())

        month_starts = db.session.query(func.count(Placement.id)).filter(
            func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM')==ym).scalar() or 0
        month_submissions = db.session.query(func.count(Candidate.id)).filter(
            func.to_char(Candidate.created_at, 'YYYY-MM')==ym).scalar() or 0
        partner_sum = db.session.query(func.coalesce(func.sum(Placement.partner_commission),0.0)).filter(
            func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM')==ym).scalar() or 0.0
        recruiter_sum = db.session.query(func.coalesce(func.sum(Placement.recruiter_commission),0.0)).filter(
            func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM')==ym).scalar() or 0.0

        # Персональные метрики рекрутёра (если текущий пользователь — рекрутёр)
        my_submissions = 0
        my_starts = 0
        my_partner_sum = 0.0
        my_recruiter_sum = 0.0
        my_status_counts = {}

        if u.role == "recruiter":
            # Подачи этого рекрутёра (кандидаты с его трудоустройствами, созданные в этом месяце)
            my_submissions = (
                db.session.query(func.count(Candidate.id))
                .join(Placement, Placement.candidate_id == Candidate.id)
                .filter(
                    Placement.recruiter_id == u.id,
                    func.to_char(Candidate.created_at, 'YYYY-MM') == ym,
                )
                .scalar()
                or 0
            )

            # Старты этого рекрутёра за месяц
            my_starts = (
                db.session.query(func.count(Placement.id))
                .filter(
                    Placement.recruiter_id == u.id,
                    func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM') == ym,
                )
                .scalar()
                or 0
            )

            # Суммы по этому рекрутёру за месяц
            my_partner_sum = (
                db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                .filter(
                    Placement.recruiter_id == u.id,
                    func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM') == ym,
                )
                .scalar()
                or 0.0
            )
            my_recruiter_sum = (
                db.session.query(func.coalesce(func.sum(Placement.recruiter_commission), 0.0))
                .filter(
                    Placement.recruiter_id == u.id,
                    func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM') == ym,
                )
                .scalar()
                or 0.0
            )

            # Воронка по статусам для кандидатов этого рекрутёра (за всё время)
            status_rows_my = (
                db.session.query(Candidate.status, func.count(Candidate.id))
                .join(Placement, Placement.candidate_id == Candidate.id)
                .filter(Placement.recruiter_id == u.id)
                .group_by(Candidate.status)
                .all()
            )
            my_status_counts = {row[0]: row[1] for row in status_rows_my}

        my_conversion = round(my_starts / my_submissions * 100.0, 1) if my_submissions else 0.0

        top_rec = db.session.execute(text("""
            SELECT u.name as name, COUNT(p.id) as starts, COALESCE(SUM(p.recruiter_commission),0) as recruiter_sum
            FROM placements p
            JOIN users u ON u.id = p.recruiter_id
            WHERE to_char(to_date(p.start_date, 'YYYY-MM-DD'), 'YYYY-MM') = :ym
            GROUP BY u.id ORDER BY starts DESC LIMIT 10
        """), {"ym": ym}).mappings().all()

        top_par = db.session.execute(text("""
            SELECT u.name as name, COUNT(p.id) as starts, COALESCE(SUM(p.partner_commission),0) as partner_sum
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN users u ON u.id = c.submitter_id
            WHERE to_char(to_date(p.start_date, 'YYYY-MM-DD'), 'YYYY-MM') = :ym
            GROUP BY u.id ORDER BY starts DESC LIMIT 10
        """), {"ym": ym}).mappings().all()

        partner_activity = db.session.execute(text("""
            SELECT
              p.id as id,
              p.name as partner_name,
              r.name as recruiter_name,
              COUNT(c.id) as submissions_total,
              SUM(CASE WHEN c.id IS NOT NULL AND to_char(c.created_at, 'YYYY-MM') = :ym THEN 1 ELSE 0 END) as submissions_month,
              COUNT(pl.id) as starts_total,
              SUM(CASE WHEN pl.id IS NOT NULL AND pl.start_date IS NOT NULL AND to_char(to_date(pl.start_date, 'YYYY-MM-DD'), 'YYYY-MM') = :ym THEN 1 ELSE 0 END) as starts_month,
              MAX(c.created_at) as last_submission_at
            FROM users p
            LEFT JOIN users r ON r.id = p.assigned_recruiter_id
            LEFT JOIN candidates c ON c.submitter_id = p.id
            LEFT JOIN placements pl ON pl.candidate_id = c.id
            WHERE p.role = 'partner'
            GROUP BY p.id
            ORDER BY submissions_month DESC, submissions_total DESC
            LIMIT 100
        """), {"ym": ym}).mappings().all()


        # Рассчитываем "здоровье" партнёров
        partner_health = []
        today = date.today()
        soft_gap = 30
        hard_gap = 60

        for row in partner_activity:
            row = dict(row)
            last_raw = row.get("last_submission_at")
            last_date = None
            days_since_last = None
            if last_raw:
                try:
                    last_dt = datetime.fromisoformat(str(last_raw))
                    last_date = last_dt.date()
                except ValueError:
                    try:
                        last_date = datetime.strptime(str(last_raw).split(" ")[0], "%Y-%m-%d").date()
                    except ValueError:
                        last_date = None
                if last_date:
                    days_since_last = (today - last_date).days

            submissions_month = row.get("submissions_month") or 0
            starts_month = row.get("starts_month") or 0

            if submissions_month > 0 or starts_month > 0:
                health_status = "green"
                health_status_label = "Активный"
            else:
                if days_since_last is None:
                    health_status = "red"
                    health_status_label = "Спит"
                elif days_since_last <= soft_gap:
                    health_status = "yellow"
                    health_status_label = "Затухает"
                elif days_since_last <= hard_gap:
                    health_status = "yellow"
                    health_status_label = "Затухает"
                else:
                    health_status = "red"
                    health_status_label = "Спит"

            base_score = submissions_month + 2 * starts_month
            if days_since_last is None:
                recency_factor = 0.2
            elif days_since_last <= 7:
                recency_factor = 1.0
            elif days_since_last <= 30:
                recency_factor = 0.7
            elif days_since_last <= 60:
                recency_factor = 0.4
            else:
                recency_factor = 0.1

            health_score = int(min(100, base_score * 10 * recency_factor))

            row["health_status"] = health_status
            row["health_status_label"] = health_status_label
            row["health_score"] = health_score
            row["days_since_last"] = days_since_last

            partner_health.append(row)

        partner_activity = partner_health

        partner_top_healthy = sorted(
            [r for r in partner_health if r.get("health_score", 0) > 0],
            key=lambda r: r.get("health_score", 0),
            reverse=True
        )[:10]

        sleepy_candidates = [r for r in partner_health if r.get("health_status") in ("yellow", "red")]
        partner_sleepy = sorted(
            sleepy_candidates,
            key=lambda r: r.get("days_since_last") if r.get("days_since_last") is not None else 9999,
            reverse=True
        )[:10]

        recruiter_partner_stats = db.session.execute(text("""
            SELECT
              r.id as id,
              r.name as recruiter_name,
              COUNT(DISTINCT p.id) as partners_total,
              COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND to_char(c.created_at, 'YYYY-MM') = :ym THEN p.id END) as active_partners_month,
              SUM(CASE WHEN c.id IS NOT NULL AND to_char(c.created_at, 'YYYY-MM') = :ym THEN 1 ELSE 0 END) as submissions_month,
              SUM(CASE WHEN pl.id IS NOT NULL AND pl.start_date IS NOT NULL AND to_char(to_date(pl.start_date, 'YYYY-MM-DD'), 'YYYY-MM') = :ym THEN 1 ELSE 0 END) as starts_month
            FROM users r
            LEFT JOIN users p ON p.assigned_recruiter_id = r.id AND p.role = 'partner'
            LEFT JOIN candidates c ON c.submitter_id = p.id
            LEFT JOIN placements pl ON pl.candidate_id = c.id
            WHERE r.role = 'recruiter'
            GROUP BY r.id
            ORDER BY partners_total DESC
        """), {"ym": ym}).mappings().all()

        partner_overview = {
            "total_partners": len(partner_activity),
            "active_partners_month": sum(1 for row in partner_activity if (row["submissions_month"] or 0) > 0),
            "submissions_month": sum(row["submissions_month"] or 0 for row in partner_activity),
            "starts_month": sum(row["starts_month"] or 0 for row in partner_activity),
        }
        active_cnt = partner_overview["active_partners_month"] or 0
        if active_cnt:
            partner_overview["avg_submissions_per_active"] = round(partner_overview["submissions_month"] / active_cnt, 1)
        else:
            partner_overview["avg_submissions_per_active"] = 0.0

        return render_template("dash_staff.html", submissions=submissions, placements=placements,
                               kpi={"month_starts": month_starts,
                                    "month_submissions": month_submissions,
                                    "month_partner_sum": round(partner_sum,2),
                                    "month_recruiter_sum": round(recruiter_sum,2),
                                    "by_recruiter": top_rec,
                                    "by_partner": top_par,
                                    "partner_overview": partner_overview,
                                    "partner_activity": partner_activity,
                                    "partner_top_healthy": partner_top_healthy,
                                    "partner_sleepy": partner_sleepy,
                                    "recruiter_partner_stats": recruiter_partner_stats,
                                    "my_submissions": my_submissions,
                                    "my_starts": my_starts,
                                    "my_partner_sum": round(my_partner_sum, 2),
                                    "my_recruiter_sum": round(my_recruiter_sum, 2),
                                    "my_conversion": my_conversion,
                                    "my_status_counts": my_status_counts})

@main_bp.route("/my-partners")
@login_required
def my_partners():
    """
    Страница для рекрутёра (и руководства) с его партнёрами и заявками партнёров.
    Пароли нигде не показываем: только имя, email, телефон и комментарии.
    """
    if g.user.role not in ("recruiter", "coordinator", "director"):
        return redirect(url_for("main.index"))

    recruiter_filter_id = None
    if g.user.role in ("coordinator", "director"):
        recruiter_filter_id = request.args.get("recruiter_id", type=int)

    ym = date.today().strftime("%Y-%m")

    # Партнёры (созданные пользователи)
    partner_query = db.session.query(User).filter(User.role == "partner")
    if g.user.role == "recruiter":
        partner_query = partner_query.filter(User.assigned_recruiter_id == g.user.id)
    elif recruiter_filter_id:
        partner_query = partner_query.filter(User.assigned_recruiter_id == recruiter_filter_id)
    partners = partner_query.order_by(User.name.asc()).all()

    partners_total = len(partners)

    # Здоровье партнёров для текущего списка
    soft_gap = 30
    hard_gap = 60
    today = date.today()
    sleepy_30 = []

    for u in partners:
        stats = db.session.execute(text("""
            SELECT
              COUNT(c.id) as submissions_total,
              SUM(CASE WHEN c.id IS NOT NULL AND to_char(c.created_at, 'YYYY-MM') = :ym THEN 1 ELSE 0 END) as submissions_month,
              COUNT(pl.id) as starts_total,
              SUM(CASE WHEN pl.id IS NOT NULL AND to_char(to_date(pl.start_date, 'YYYY-MM-DD'), 'YYYY-MM') = :ym THEN 1 ELSE 0 END) as starts_month,
              MAX(c.created_at) as last_submission_at
            FROM candidates c
            LEFT JOIN placements pl ON pl.candidate_id = c.id
            WHERE c.submitter_id = :pid
        """), {"ym": ym, "pid": u.id}).mappings().first()

        last_raw = stats["last_submission_at"] if stats else None
        last_date = None
        days_since_last = None
        if last_raw:
            try:
                last_dt = datetime.fromisoformat(str(last_raw))
                last_date = last_dt.date()
            except ValueError:
                try:
                    last_date = datetime.strptime(str(last_raw).split(" ")[0], "%Y-%m-%d").date()
                except ValueError:
                    last_date = None
            if last_date:
                days_since_last = (today - last_date).days

        submissions_month = (stats["submissions_month"] if stats else 0) or 0
        starts_month = (stats["starts_month"] if stats else 0) or 0

        if submissions_month > 0 or starts_month > 0:
            health_status = "green"
            health_status_label = "Активный"
        else:
            if days_since_last is None:
                health_status = "red"
                health_status_label = "Спит"
            elif days_since_last <= soft_gap:
                health_status = "yellow"
                health_status_label = "Затухает"
            elif days_since_last <= hard_gap:
                health_status = "yellow"
                health_status_label = "Затухает"
            else:
                health_status = "red"
                health_status_label = "Спит"

        base_score = submissions_month + 2 * starts_month
        if days_since_last is None:
            recency_factor = 0.2
        elif days_since_last <= 7:
            recency_factor = 1.0
        elif days_since_last <= 30:
            recency_factor = 0.7
        elif days_since_last <= 60:
            recency_factor = 0.4
        else:
            recency_factor = 0.1

        health_score = int(min(100, base_score * 10 * recency_factor))

        u.health_status = health_status
        u.health_status_label = health_status_label
        u.health_score = health_score
        u.days_since_last = days_since_last

        if days_since_last is not None and days_since_last >= 30:
            sleepy_30.append(u)

    # Уведомление рекрутёру о "заснувших" партнёрах (без подач >= 30 дней)
    if g.user.role == "recruiter" and sleepy_30:
        msg = f"У тебя {len(sleepy_30)} партнёров без подач больше 30 дней."
        existing_note = (
            db.session.query(Notification)
            .filter(Notification.user_id == g.user.id, Notification.message == msg, Notification.is_read == False)
            .first()
        )
        if not existing_note:
            create_notification_for_users([g.user.id], msg)
            db.session.commit()

    # Новые партнёры в этом месяце (по одобренным заявкам)
    new_partners_q = db.session.query(func.count(RegistrationRequest.id)).filter(
        RegistrationRequest.role == "partner",
        RegistrationRequest.status == "approved",
        func.to_char(RegistrationRequest.created_at, 'YYYY-MM') == ym,
    )
    if g.user.role == "recruiter":
        new_partners_q = new_partners_q.filter(RegistrationRequest.assigned_recruiter_id == g.user.id)
    elif recruiter_filter_id:
        new_partners_q = new_partners_q.filter(RegistrationRequest.assigned_recruiter_id == recruiter_filter_id)
    new_partners_month = new_partners_q.scalar() or 0

    # Заявки партнёров
    status = request.args.get("status") or "new"
    req_query = db.session.query(RegistrationRequest).filter(RegistrationRequest.role == "partner")
    if g.user.role == "recruiter":
        req_query = req_query.filter(RegistrationRequest.assigned_recruiter_id == g.user.id)
    elif recruiter_filter_id:
        req_query = req_query.filter(RegistrationRequest.assigned_recruiter_id == recruiter_filter_id)
    if status != "all":
        req_query = req_query.filter(RegistrationRequest.status == status)
    requests = req_query.order_by(RegistrationRequest.created_at.desc()).limit(200).all()

    recruiters = []
    if g.user.role in ("coordinator", "director"):
        recruiters = (
            db.session.query(User)
            .filter(User.role == "recruiter", User.is_active == True)
            .order_by(User.name.asc())
            .all()
        )

    return render_template(
        "my_partners.html",
        partners=partners,
        requests=requests,
        status=status,
        recruiters=recruiters,
        recruiter_filter_id=recruiter_filter_id,
        partners_total=partners_total,
        new_partners_month=new_partners_month,
    )




@main_bp.route("/inbox")
@login_required
def inbox():
    if g.user.role not in ("recruiter","coordinator","director"):
        return redirect(url_for("main.index"))
    rows = (db.session.query(Candidate, case((Job.status=="active", Job.title), else_=None).label("job_title"), User.name.label("submitter_name"), User.note.label("submitter_note"))
            .join(Job, Candidate.job_id==Job.id)
            .join(User, User.id==Candidate.submitter_id)
            .filter(Candidate.status=="Подан")
            .order_by(Candidate.created_at.desc()).limit(300).all())
    return render_template("inbox.html", rows=rows)


@main_bp.route("/analytics")
@login_required
@roles_required("coordinator")
def analytics():
    """Аналитика с фильтрами по месяцу, рекрутёру, партнёру и вакансии."""
    ym = request.args.get("ym") or date.today().strftime("%Y-%m")
    recruiter_id = request.args.get("recruiter_id", type=int)
    partner_id = request.args.get("partner_id", type=int)
    job_id = request.args.get("job_id", type=int)

    # Базовый фильтр по месяцу (по дате старта)
    filters = [func.to_char(func.to_date(Placement.start_date, 'YYYY-MM-DD'), 'YYYY-MM') == ym]

    if recruiter_id:
        filters.append(Placement.recruiter_id == recruiter_id)
    if partner_id:
        filters.append(Candidate.submitter_id == partner_id)
    if job_id:
        filters.append(Placement.job_id == job_id)

    # Итоги по периоду
    total_starts = (
        db.session.query(func.count(Placement.id))
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(*filters)
        .scalar()
        or 0
    )
    total_partner_sum = (
        db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(*filters)
        .scalar()
        or 0.0
    )
    total_recruiter_sum = (
        db.session.query(func.coalesce(func.sum(Placement.recruiter_commission), 0.0))
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(*filters)
        .scalar()
        or 0.0
    )

    # Разбивка по рекрутёрам
    Recruiter = aliased(User)
    by_recruiter = (
        db.session.query(
            Recruiter.id.label("id"),
            Recruiter.name.label("name"),
            func.count(Placement.id).label("starts"),
            func.coalesce(func.sum(Placement.partner_commission), 0.0).label("partner_sum"),
            func.coalesce(func.sum(Placement.recruiter_commission), 0.0).label("recruiter_sum"),
        )
        .join(Recruiter, Recruiter.id == Placement.recruiter_id)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(*filters, Recruiter.role == "recruiter")
        .group_by(Recruiter.id)
        .order_by(func.count(Placement.id).desc())
        .all()
    )

    # Разбивка по партнёрам
    Partner = aliased(User)
    by_partner = (
        db.session.query(
            Partner.id.label("id"),
            Partner.name.label("name"),
            func.count(Placement.id).label("starts"),
            func.coalesce(func.sum(Placement.partner_commission), 0.0).label("partner_sum"),
        )
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .join(Partner, Partner.id == Candidate.submitter_id)
        .filter(*filters, Partner.role == "partner")
        .group_by(Partner.id)
        .order_by(func.count(Placement.id).desc())
        .all()
    )

    # Разбивка по вакансиям
    by_job = (
        db.session.query(
            Job.id.label("id"),
            Job.title.label("title"),
            func.count(Placement.id).label("starts"),
            func.coalesce(func.sum(Placement.partner_commission), 0.0).label("partner_sum"),
        )
        .join(Job, Job.id == Placement.job_id)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(*filters)
        .group_by(Job.id)
        .order_by(func.count(Placement.id).desc())
        .all()
    )

    # Справочники для фильтров
    recruiters = (
        db.session.query(User)
        .filter(User.role == "recruiter", User.is_active == True)
        .order_by(User.name.asc())
        .all()
    )
    partners = (
        db.session.query(User)
        .filter(User.role == "partner", User.is_active == True)
        .order_by(User.name.asc())
        .all()
    )
    jobs = db.session.query(Job).order_by(Job.title.asc()).all()

    current_filters = {
        "ym": ym,
        "recruiter_id": recruiter_id,
        "partner_id": partner_id,
        "job_id": job_id,
    }

    return render_template(
        "analytics.html",
        ym=ym,
        current_filters=current_filters,
        total={"starts": total_starts,
               "partner_sum": total_partner_sum,
               "recruiter_sum": total_recruiter_sum},
        by_recruiter=by_recruiter,
        by_partner=by_partner,
        by_job=by_job,
        recruiters=recruiters,
        partners=partners,
        jobs=jobs,
    )
