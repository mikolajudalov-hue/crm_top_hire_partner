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


partner_bp = Blueprint('partner', __name__)

@partner_bp.route("/partner/profile", methods=["GET", "POST"])
@login_required
@roles_required("partner")
def partner_profile():
    u = db.session.get(User, g.user.id)
    if not u:
        abort(404)

    if request.method == "POST":
        u.bank_account = (request.form.get("bank_account") or "").strip()
        u.bank_name = (request.form.get("bank_name") or "").strip()
        u.company_name = (request.form.get("company_name") or "").strip()
        u.tax_id = (request.form.get("tax_id") or "").strip()
        u.address = (request.form.get("address") or "").strip()
        u.payout_note = (request.form.get("payout_note") or "").strip()
        # Тип партнёра: фрилансер или фирма
        u.partner_type = (request.form.get("partner_type") or (u.partner_type or "freelancer")).strip()

        current_password = request.form.get("current_password") or ""
        new_password = (request.form.get("new_password") or "").strip()
        new_password2 = (request.form.get("new_password2") or "").strip()

        # Если партнёр заполнил поля нового пароля — пытаемся сменить пароль
        if new_password or new_password2:
            if not current_password:
                flash("Укажите текущий пароль, чтобы изменить пароль.", "danger")
                return redirect(url_for("partner.partner_profile"))
            if not check_password_hash(u.password_hash, current_password):
                flash("Текущий пароль указан неверно.", "danger")
                return redirect(url_for("partner.partner_profile"))
            if new_password != new_password2:
                flash("Новый пароль и подтверждение не совпадают.", "danger")
                return redirect(url_for("partner.partner_profile"))
            if len(new_password) < 4:
                flash("Новый пароль слишком короткий. Минимум 4 символа.", "danger")
                return redirect(url_for("partner.partner_profile"))

            u.password_hash = generate_password_hash(new_password)
            flash("Пароль успешно изменён.", "success")

        db.session.commit()

        # Проверяем чек-лист онбординга и уведомляем рекрутёра при полном завершении
        profile_filled = bool(u.bank_account and u.bank_name and u.company_name and u.tax_id and u.address)
        first_candidate = (
            db.session.query(Candidate)
            .filter(Candidate.submitter_id == u.id)
            .order_by(Candidate.created_at.asc())
            .first()
        )
        has_candidate = first_candidate is not None
        has_submission = has_candidate  # факт кандидата = поданная заявка
        status_updated = bool(first_candidate and first_candidate.status and first_candidate.status != "Подан")

        if profile_filled and has_candidate and has_submission and status_updated and u.assigned_recruiter_id:
            msg = f"Партнёр {u.name} ({u.email}) полностью прошёл онбординг."
            existing_onb = (
                db.session.query(Notification)
                .filter(Notification.user_id == u.assigned_recruiter_id, Notification.message == msg)
                .first()
            )
            if not existing_onb:
                create_notification_for_users([u.assigned_recruiter_id], msg)
                db.session.commit()

        file = request.files.get("doc_file")
        doc_label = (request.form.get("doc_label") or "").strip()
        if file and file.filename:
            upload_root = os.path.join(os.path.dirname(__file__), "uploads", "partner_docs")
            os.makedirs(upload_root, exist_ok=True)
            safe_name = secure_filename(file.filename)
            partner_dir = os.path.join(upload_root, str(u.id))
            os.makedirs(partner_dir, exist_ok=True)
            save_path = os.path.join(partner_dir, safe_name)
            file.save(save_path)
            rel_name = f"{u.id}/{safe_name}"
            doc = PartnerDoc(partner_id=u.id, filename=rel_name, label=doc_label)
            db.session.add(doc)
            db.session.commit()
            flash("Документ загружен", "success")

        flash("Данные профиля сохранены", "success")
        return redirect(url_for("partner.partner_profile"))

    docs = (
        db.session.query(PartnerDoc)
        .filter(PartnerDoc.partner_id == g.user.id)
        .order_by(PartnerDoc.uploaded_at.desc())
        .all()
    )

    # Чек-лист онбординга для отображения
    profile_filled = bool(u.bank_account and u.bank_name and u.company_name and u.tax_id and u.address)
    first_candidate = (
        db.session.query(Candidate)
        .filter(Candidate.submitter_id == u.id)
        .order_by(Candidate.created_at.asc())
        .first()
    )
    has_candidate = first_candidate is not None
    has_submission = has_candidate
    status_updated = bool(first_candidate and first_candidate.status and first_candidate.status != "Подан")

    onboarding = {
        "profile_filled": profile_filled,
        "has_candidate": has_candidate,
        "has_submission": has_submission,
        "status_updated": status_updated,
    }
    onboarding_done = all(onboarding.values())

    return render_template("partner_profile.html", user=u, docs=docs, onboarding=onboarding, onboarding_done=onboarding_done)


@partner_bp.route("/partner/help")
@login_required
@roles_required("partner")
def partner_help():
    """Страница с инструкцией для партнёра и relax-зоной."""

    max_auto_shows = 3
    auto_display = False

    # Если пришли сюда автоматически после входа
    if session.pop("partner_help_auto", False):
        auto_display = True
        shown = session.get("partner_help_shown", 0) + 1
        session["partner_help_shown"] = shown
    else:
        shown = session.get("partner_help_shown", 0)

    remaining = max(max_auto_shows - shown, 0)
    # Показываем текст «эта инструкция появится ещё N раз» только при автоматическом показе
    if not auto_display or remaining <= 0:
        remaining = None

    return render_template("partner_help.html", remaining_help_shows=remaining)


@partner_bp.route("/partner-doc/<int:doc_id>")
@login_required
def partner_doc(doc_id):
    d = db.session.get(PartnerDoc, doc_id)
    if not d:
        abort(404)

    # Проверка прав: партнёр может смотреть только свои документы,
    # координатор/финансы — любые.
    if g.user.role == "partner":
        if d.partner_id != g.user.id:
            abort(403)
    elif g.user.role not in ("coordinator", "director", "finance"):
        abort(403)

    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "partner_docs")
    return send_from_directory(upload_root, d.filename)



@partner_bp.route("/partner/earnings")
@login_required
@roles_required("partner")
def partner_earnings():
    """Сводка начислений партнёра по месяцам + детализация по кандидатам."""
    u = g.user

    # Агрегированная статистика по месяцам
    rows = db.session.execute(
        text(
            """
            SELECT 
              strftime('%Y-%m', p.start_date) AS ym,
              COUNT(p.id) AS starts,
              COALESCE(SUM(
                CASE 
                  WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 THEN p.partner_commission
                  WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 THEN j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
                  ELSE 0 END
              ),0) AS total
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN jobs j ON j.id = p.job_id
            WHERE c.submitter_id = :pid
            GROUP BY ym
            ORDER BY ym DESC
            """
        ),
        {"pid": u.id},
    ).mappings().all()

    total_all = sum(r["total"] for r in rows)

    # Детализация по кандидатам в разрезе месяцев
    placements = (
        db.session.query(Placement, Candidate, Job)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .join(Job, Job.id == Placement.job_id)
        .filter(Candidate.submitter_id == u.id)
        .order_by(Placement.start_date.desc())
        .all()
    )


    details_by_month = {}

    for pl, cand, job in placements:
        if not pl.start_date:
            continue

        # start_date хранится как строка YYYY-MM-DD, поэтому аккуратно получаем YYYY-MM
        if isinstance(pl.start_date, str):
            ym = pl.start_date[:7]
        else:
            ym = pl.start_date.strftime("%Y-%m")

        amount = pl.partner_commission or 0.0
        if not amount:
            if job.partner_fee_amount and job.partner_fee_amount > 0:
                promo = job.promo_multiplier or 1.0
                amount = (job.partner_fee_amount or 0.0) * promo

        details_by_month.setdefault(ym, []).append(
            {
                "candidate_name": cand.full_name,
                "job_title": job.title,
                "start_date": pl.start_date,
                "amount": amount,
            }
        )

    return render_template(
        "partner_earnings.html",
        rows=rows,
        total_all=total_all,
        details_by_month=details_by_month,
    )



@partner_bp.route("/partner/payouts")
@login_required
@roles_required("partner")
def partner_payouts():
    """История выплат для партнёра: сгруппировано по месяцам и файлу оплаты."""
    u = g.user

    # Все оплаченные оформления этого партнёра
    rows = (
        db.session.query(Placement, Candidate, Job)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .join(Job, Job.id == Placement.job_id)
        .filter(
            Candidate.submitter_id == u.id,
            Placement.partner_paid == True,
            Placement.partner_paid_at.isnot(None),
        )
        .order_by(Placement.partner_paid_at.desc(), Placement.id.desc())
        .all()
    )

    payouts = []
    key_map = {}

    for pl, cand, job in rows:
        if not pl.partner_paid_at:
            continue

        ym = pl.partner_paid_at.strftime("%Y-%m")
        payment_file = pl.partner_payment_file or ""
        key = (ym, payment_file)

        if key not in key_map:
            payout = {
                "ym": ym,
                "paid_at": pl.partner_paid_at,
                "payment_file": pl.partner_payment_file,
                "example_placement_id": pl.id,
                "candidates": [],
                "total_amount": 0.0,
                "count": 0,
            }
            payouts.append(payout)
            key_map[key] = payout

        payout = key_map[key]

        # Сумма по кандидату такая же логика, как в других отчётах
        amount = pl.partner_commission or 0.0
        if not amount:
            if job.partner_fee_amount:
                promo = job.promo_multiplier or 1.0
                amount = (job.partner_fee_amount or 0.0) * promo

        payout["candidates"].append(
            {
                "candidate_name": cand.full_name,
                "job_title": job.title,
                "start_date": pl.start_date,
                "amount": amount,
            }
        )
        payout["total_amount"] += amount
        payout["count"] += 1

    # Сортировка по дате оплаты (сначала свежие)
    payouts.sort(key=lambda p: p["paid_at"] or datetime.min, reverse=True)

    grand_total = sum(p["total_amount"] for p in payouts)
    grand_count = sum(p["count"] for p in payouts)

    return render_template(
        "partner_payouts.html",
        payouts=payouts,
        grand_total=grand_total,
        grand_count=grand_count,
    )


@partner_bp.route("/partner/reports")
@login_required
@roles_required("partner")
def partner_reports():
    u = g.user
    from datetime import date

    period = request.args.get("period", "month")
    today = date.today()

    # Определяем начальную дату для выбранного периода
    if period == "year":
        start = date(today.year, 1, 1)
    elif period == "quarter":
        q_start_month = 1 + 3 * ((today.month - 1) // 3)
        start = date(today.year, q_start_month, 1)
    elif period == "all":
        start = None
    else:
        # месяц по умолчанию
        start = date(today.year, today.month, 1)

    start_str = start.isoformat() if start else None
    end_str = today.isoformat()

    # Базовый запрос по кандидатам этого партнёра
    from sqlalchemy import func

    cand_query = db.session.query(Candidate).filter(Candidate.submitter_id == u.id)
    if start_str:
        cand_query = cand_query.filter(
            func.date(Candidate.created_at) >= start_str,
            func.date(Candidate.created_at) <= end_str,
        )

    candidates_all = cand_query.subquery()

    total_created = db.session.query(func.count(candidates_all.c.id)).scalar() or 0

    # По статусам
    started_statuses = ["Вышел на работу", "Отработал месяц"]
    failed_statuses = ["Не вышел", "Не отработал"]

    total_started = db.session.query(func.count(candidates_all.c.id)).filter(
        candidates_all.c.status.in_(started_statuses)
    ).scalar() or 0

    total_failed = db.session.query(func.count(candidates_all.c.id)).filter(
        candidates_all.c.status.in_(failed_statuses)
    ).scalar() or 0

    total_worked_month = db.session.query(func.count(candidates_all.c.id)).filter(
        candidates_all.c.status == "Отработал месяц"
    ).scalar() or 0

    # Оформления (placements) и деньги
    place_query = (
        db.session.query(Placement)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(Candidate.submitter_id == u.id)
    )
    if start_str:
        place_query = place_query.filter(
            Placement.start_date >= start_str,
            Placement.start_date <= end_str,
        )

    placements = place_query.all()
    placements_count = len(placements)

    potential_sum = sum(p.partner_commission or 0.0 for p in placements)

    # Выплачено за период
    paid_query = (
        db.session.query(Placement)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .filter(
            Candidate.submitter_id == u.id,
            Placement.partner_paid == True,
            Placement.partner_paid_at.isnot(None),
        )
    )
    if start_str:
        paid_query = paid_query.filter(
            func.date(Placement.partner_paid_at) >= start_str,
            func.date(Placement.partner_paid_at) <= end_str,
        )

    paid_placements = paid_query.all()
    paid_sum = sum(p.partner_commission or 0.0 for p in paid_placements)

    # Остаток к выплате за период
    balance_period = potential_sum - paid_sum

    # Конверсии (в процентах)
    conv_started = (total_started / total_created * 100) if total_created else 0.0
    conv_worked_month = (total_worked_month / total_created * 100) if total_created else 0.0

    period_label = {
        "month": "Текущий месяц",
        "quarter": "Текущий квартал",
        "year": "Текущий год",
        "all": "За всё время",
    }.get(period, "Текущий месяц")

    return render_template(
        "partner_reports.html",
        period=period,
        period_label=period_label,
        totals={
            "created": total_created,
            "started": total_started,
            "failed": total_failed,
            "worked_month": total_worked_month,
            "placements": placements_count,
            "potential_sum": round(potential_sum, 2),
            "paid_sum": round(paid_sum, 2),
            "balance_period": round(balance_period, 2),
            "conv_started": round(conv_started, 1),
            "conv_worked_month": round(conv_worked_month, 1),
        },
        paid_placements=paid_placements,
        period_start=start_str,
        period_end=end_str,
    )
