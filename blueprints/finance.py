from datetime import date, datetime
import calendar
import os

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, g, abort, flash, send_from_directory
)
from werkzeug.utils import secure_filename
from sqlalchemy import func, text
from sqlalchemy.orm import aliased

from models import (
    db,
    User,
    Job,
    Candidate,
    Placement,
    Notification,
    create_notification_for_users,
    BillingPeriod,
    PartnerDoc,
    CandidateProfile,
    CandidateDoc,
    News,
    RelaxHistory,
    RegistrationRequest,

)
from auth_utils import login_required, roles_required


finance_bp = Blueprint("finance", __name__)


# ================================================================
#                          REPORTS
# ================================================================
@finance_bp.route("/reports")
@login_required
@roles_required("recruiter", "coordinator")
def reports():
    ym = request.args.get("month") or date.today().strftime("%Y-%m")

    rows = (
        db.session.query(
            Placement,
            Candidate.full_name.label("cand_name"),
            Job.title.label("job_title"),
            db.session.query(User.name)
                .filter(User.id == Candidate.submitter_id)
                .correlate(Candidate)
                .scalar_subquery()
                .label("partner_name"),
            User.name.label("recruiter_name"),
        )
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .join(Job, Job.id == Placement.job_id)
        .join(User, User.id == Placement.recruiter_id)
        .filter(func.strftime("%Y-%m", Placement.start_date) == ym)
        .order_by(Placement.start_date.asc())
        .all()
    )

    return render_template("reports.html", rows=rows, ym=ym)


# ================================================================
#                         DASHBOARD
# ================================================================
@finance_bp.route("/finance")
@login_required
@roles_required("coordinator", "finance")
def finance_dashboard():
    total_periods = db.session.query(func.count(BillingPeriod.id)).scalar() or 0
    total_amount = (
        db.session.query(func.coalesce(func.sum(BillingPeriod.total_amount), 0.0))
        .scalar() or 0.0
    )
    total_placements = db.session.query(func.count(Placement.id)).scalar() or 0

    return render_template(
        "finance_dashboard.html",
        total_periods=total_periods,
        total_amount=round(total_amount, 2),
        total_placements=total_placements,
    )


# ================================================================
#                    PARTNERS + STATS
# ================================================================
@finance_bp.route("/finance/partners")
@login_required
@roles_required("coordinator", "finance")
def finance_partners():
    partners = (
        db.session.query(User)
        .filter(User.role == "partner")
        .order_by(User.name.asc())
        .all()
    )

    rows = db.session.execute(
        text(
            """
            SELECT c.submitter_id AS pid,
                   COUNT(p.id) AS starts,
                   COALESCE(SUM(
                     CASE 
                       WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 
                       THEN p.partner_commission
                       WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 
                       THEN j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
                       ELSE 0 END
                   ),0) AS total
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN jobs j ON j.id = p.job_id
            GROUP BY c.submitter_id
            """
        )
    ).mappings().all()

    stat_map = {row["pid"]: row for row in rows}

    return render_template("finance_partners.html", partners=partners, stat_map=stat_map)


@finance_bp.route("/finance/partners/<int:pid>")
@login_required
@roles_required("coordinator", "finance")
def finance_partner_view(pid):
    partner = db.session.get(User, pid)
    if not partner or partner.role != "partner":
        abort(404)

    docs = (
        db.session.query(PartnerDoc)
        .filter(PartnerDoc.partner_id == pid)
        .order_by(PartnerDoc.uploaded_at.desc())
        .all()
    )

    rows = db.session.execute(
        text(
            """
            SELECT 
              strftime('%Y-%m', p.start_date) AS ym,
              COUNT(p.id) AS starts,
              COALESCE(SUM(
                CASE 
                  WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 THEN p.partner_commission
                  WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 
                  THEN j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
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
        {"pid": pid},
    ).mappings().all()

    total_all = sum(r["total"] for r in rows) if rows else 0

    return render_template(
        "finance_partner_view.html",
        partner=partner,
        docs=docs,
        rows=rows,
        total_all=total_all,
    )


# ================================================================
#                        PAYMENTS
# ================================================================
@finance_bp.route("/finance/payments")
@login_required
@roles_required("coordinator", "finance")
def finance_payments():
    """Все кандидаты, которые достигли 30 дней и подлежат выплате партнёрам."""

    as_of = request.args.get("as_of") or date.today().strftime("%Y-%m-%d")
    show_all = request.args.get("show_all") == "1"

    rows = db.session.execute(
        text(
            """
            SELECT 
              p.id AS placement_id,
              p.start_date AS start_date,
              p.partner_paid AS partner_paid,
              p.partner_paid_at AS partner_paid_at,
              c.full_name AS cand_name,
              j.title AS job_title,
              u.name AS partner_name,
              u.id AS partner_id,
              u.bank_account AS bank_account,
              u.settlement_day AS settlement_day,
              CASE 
                WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 
                THEN p.partner_commission
                WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 
                THEN j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
                ELSE 0 END AS amount,
              CAST(julianday(:as_of) - julianday(p.start_date) AS INTEGER) AS days_worked
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN jobs j ON j.id = p.job_id
            JOIN users u ON u.id = c.submitter_id
            WHERE p.start_date IS NOT NULL
              AND CAST(julianday(:as_of) - julianday(p.start_date) AS INTEGER) >= 30
              AND (p.partner_paid IS NULL OR p.partner_paid = 0)
            ORDER BY u.name ASC, p.start_date ASC
            """
        ),
        {"as_of": as_of},
    ).mappings().all()
    # Конвертируем RowMapping в обычные dict, чтобы можно было
    # добавлять служебные поля (next_pay_date, days_until_pay).
    rows = [dict(r) for r in rows]

    try:
        as_of_date = date.fromisoformat(as_of)
    except:
        as_of_date = date.today()

    per_partner = {}
    due_today_total = 0
    due_week_total = 0
    rows_pay_now = []
    rows_accrued = []


    for r in rows:
        pid = r["partner_id"]
        settlement_day = (r.get("settlement_day") or 0)

        # Считаем ближайшую дату выплаты (для KPI и правой таблицы)
        next_pay_date = None
        days_until_pay = None
        if settlement_day and 1 <= settlement_day <= 31:
            year = as_of_date.year
            month = as_of_date.month
            # День выплат в текущем месяце
            last_day = calendar.monthrange(year, month)[1]
            pay_day_this = min(settlement_day, last_day)
            pay_date_this = date(year, month, pay_day_this)

            if as_of_date <= pay_date_this:
                next_pay_date = pay_date_this
            else:
                # Следующий месяц
                if month == 12:
                    year2 = year + 1
                    month2 = 1
                else:
                    year2 = year
                    month2 = month + 1
                last_day_next = calendar.monthrange(year2, month2)[1]
                pay_day_next = min(settlement_day, last_day_next)
                next_pay_date = date(year2, month2, pay_day_next)

            days_until_pay = (next_pay_date - as_of_date).days

        # Заполняем агрегат по партнёрам
        entry = per_partner.setdefault(
            pid,
            {
                "partner_name": r["partner_name"],
                "bank_account": r["bank_account"],
                "settlement_day": settlement_day,
                "next_pay_date": next_pay_date,
                "days_until_pay": days_until_pay,
                "total": 0.0,
                "count": 0,
                "jobs": {},
            },
        )

        entry["total"] += r["amount"]
        entry["count"] += 1

        job_title = r["job_title"] or "Без названия"
        job_entry = entry["jobs"].setdefault(job_title, {"count": 0, "amount": 0})
        job_entry["count"] += 1
        job_entry["amount"] += r["amount"]

        # Распределение по блокам:
        # 1) "К выплате в этот расчётный период":
        #    - если день выплат не задан (0), платим сразу
        #    - если день выплат задан и уже наступил в текущем месяце
        # 2) "Накоплено, но день выплаты ещё не наступил" — остальное.
        if not settlement_day:
            # День выплат не задан — можно платить сразу
            rows_pay_now.append(r)
        else:
            # День выплат задан
            if as_of_date.day >= settlement_day:
                # День выплат в этом месяце уже прошёл (или сегодня) — платим
                rows_pay_now.append(r)
            else:
                # День выплат ещё впереди
                rows_accrued.append(r)

        # KPI "К выплате сегодня" считаем по тем, у кого день выплат сегодня
        if settlement_day and as_of_date.day == settlement_day:
            due_today_total += r["amount"]

        # KPI "В ближайшие 7 дней" считаем по ближайшей дате выплаты
        if days_until_pay is not None and 0 <= days_until_pay <= 7:
            due_week_total += r["amount"]

    sorted_partners = sorted(
        per_partner.values(),
        key=lambda x: (x["days_until_pay"] if x["days_until_pay"] is not None else 9999,
                       x["partner_name"])
    )

    partners_due_now = [p for p in sorted_partners if p["days_until_pay"] == 0]
    partners_future = [p for p in sorted_partners if p["days_until_pay"] not in (None, 0)]
    partners_no_schedule = [p for p in sorted_partners if p["settlement_day"] in (None, 0)]

    # Агрегация только по тем, кому платим сейчас (для компактной таблицы по партнёрам)
    pay_now_per_partner: dict[int, dict] = {}
    for r in rows_pay_now:
        pid = r["partner_id"]
        agg = pay_now_per_partner.setdefault(
            pid,
            {
                "partner_id": pid,
                "partner_name": r["partner_name"],
                "settlement_day": r.get("settlement_day"),
                "count": 0,
                "total_amount": 0.0,
                "total_days": 0,
            },
        )
        agg["count"] += 1
        agg["total_amount"] += r["amount"]
        agg["total_days"] += (r.get("days_worked") or 0)

    pay_now_by_partner = sorted(pay_now_per_partner.values(), key=lambda x: x["partner_name"])

    return render_template(
        "finance_payments.html",
        rows=rows,
        pay_now_rows=rows_pay_now,
        future_rows=rows_accrued,
        per_partner=per_partner,
        partners_sorted=sorted_partners,
        partners_due_now=partners_due_now,
        partners_future=partners_future,
        partners_no_schedule=partners_no_schedule,
        due_today_total=round(due_today_total, 2),
        due_week_total=round(due_week_total, 2),
        as_of=as_of,
        show_all=show_all,
        pay_now_by_partner=pay_now_by_partner,
    )


# ================================================================
#                    MARK PARTNER PAYMENT DONE
# ================================================================


# ================================================================
#              PARTNER MONTHLY PAYMENT (BATCH)
# ================================================================
@finance_bp.route("/finance/payments/partner/<int:partner_id>", methods=["GET", "POST"])
@login_required
@roles_required("coordinator", "finance")
def finance_partner_payment(partner_id):
    """Страница для выплаты одному партнёру за расчётный месяц.

    Показывает список всех кандидатов партнёра, которые попадают
    в блок "К выплате в этот расчётный период" на дату as_of,
    суммирует их и позволяет загрузить один файл подтверждения
    для всей выплаты.
    """
    as_of = request.args.get("as_of") or date.today().strftime("%Y-%m-%d")
    try:
        as_of_date = date.fromisoformat(as_of)
    except Exception:
        as_of_date = date.today()
        as_of = as_of_date.strftime("%Y-%m-%d")

    partner = db.session.get(User, partner_id)
    if not partner or partner.role != "partner":
        abort(404)

    # Те же базовые правила, что и в finance_payments
    rows = db.session.execute(
        text(
            """
            SELECT 
              p.id AS placement_id,
              p.start_date AS start_date,
              p.partner_paid AS partner_paid,
              p.partner_paid_at AS partner_paid_at,
              c.full_name AS cand_name,
              j.title AS job_title,
              u.name AS partner_name,
              u.id AS partner_id,
              u.bank_account AS bank_account,
              u.settlement_day AS settlement_day,
              CASE 
                WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 
                THEN p.partner_commission
                WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 
                THEN j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
                ELSE 0 END AS amount,
              CAST(julianday(:as_of) - julianday(p.start_date) AS INTEGER) AS days_worked
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN jobs j ON j.id = p.job_id
            JOIN users u ON u.id = c.submitter_id
            WHERE p.start_date IS NOT NULL
              AND CAST(julianday(:as_of) - julianday(p.start_date) AS INTEGER) >= 30
              AND (p.partner_paid IS NULL OR p.partner_paid = 0)
              AND u.id = :partner_id
            ORDER BY p.start_date ASC
            """
        ),
        {"as_of": as_of, "partner_id": partner_id},
    ).mappings().all()

    rows = [dict(r) for r in rows]

    candidates_to_pay = []
    total_amount = 0.0

    for r in rows:
        settlement_day = (r.get("settlement_day") or 0)
        # та же логика: если день выплат не задан или уже наступил в этом месяце — платим
        if not settlement_day or as_of_date.day >= settlement_day:
            candidates_to_pay.append(r)
            total_amount += r["amount"]

    # Удобная подпись периода, просто месяц и год
    period_label = as_of_date.strftime("%m.%Y")

    if request.method == "POST" and candidates_to_pay:
        file = request.files.get("payment_file")
        filename = None
        if file and file.filename:
            pay_dir = os.path.join(os.path.dirname(__file__), "uploads", "payments")
            os.makedirs(pay_dir, exist_ok=True)
            safe_name = secure_filename(file.filename)
            path = os.path.join(pay_dir, f"partner_{partner_id}_{as_of}_{safe_name}")
            file.save(path)
            filename = os.path.basename(path)

        placement_ids = [r["placement_id"] for r in candidates_to_pay]
        now = datetime.utcnow()

        placements = (
            db.session.query(Placement)
            .filter(Placement.id.in_(placement_ids))
            .all()
        )

        for pl in placements:
            pl.partner_paid = True
            pl.partner_paid_at = now
            if filename:
                pl.partner_payment_file = filename

            # уведомления партнёру и его рекрутеру
            cand = db.session.get(Candidate, pl.candidate_id)
            recipients = set()
            if partner and partner.id and partner.id != g.user.id:
                recipients.add(partner.id)
            if partner and partner.assigned_recruiter_id and partner.assigned_recruiter_id != g.user.id:
                recipients.add(partner.assigned_recruiter_id)
            if recipients and cand:
                create_notification_for_users(
                    recipients,
                    f"Выплата по кандидату {cand.full_name} отмечена как выполненная.",
                )

        db.session.commit()
        flash("Выплата партнёру за период отмечена как оплаченная.", "success")
        return redirect(url_for("finance.finance_payments", as_of=as_of))

    return render_template(
        "finance_partner_payment.html",
        partner=partner,
        as_of=as_of,
        period_label=period_label,
        candidates=candidates_to_pay,
        total_amount=total_amount,
    )


@finance_bp.route("/finance/payments/<int:placement_id>", methods=["GET", "POST"])
@login_required
@roles_required("coordinator", "finance")
def finance_payment_detail(placement_id):
    pl = db.session.get(Placement, placement_id)
    if not pl:
        abort(404)

    cand = db.session.get(Candidate, pl.candidate_id)
    job = db.session.get(Job, pl.job_id)
    partner = db.session.get(User, cand.submitter_id)

    if request.method == "POST":
        file = request.files.get("payment_file")
        filename = pl.partner_payment_file or ""

        if file and file.filename:
            pay_dir = os.path.join(os.path.dirname(__file__), "uploads", "payments")
            os.makedirs(pay_dir, exist_ok=True)
            safe_name = secure_filename(file.filename)
            path = os.path.join(pay_dir, f"pl_{placement_id}_{safe_name}")
            file.save(path)
            filename = os.path.basename(path)

        pl.partner_paid = True
        pl.partner_paid_at = datetime.utcnow()
        pl.partner_payment_file = filename

        # Уведомления о выплате партнёру
        recipients = set()
        # Партнёр, которому платим
        if partner and partner.id and partner.id != g.user.id:
            recipients.add(partner.id)
        # Рекрутёр, который ведёт этого партнёра
        if partner and partner.assigned_recruiter_id and partner.assigned_recruiter_id != g.user.id:
            recipients.add(partner.assigned_recruiter_id)
        if recipients:
            create_notification_for_users(
                recipients,
                f"Выплата по кандидату {cand.full_name} отмечена как выполненная."
            )

        db.session.commit()

        flash("Выплата отмечена.", "success")
        return redirect(url_for("finance.finance_payments"))

    amount = (
        job.partner_fee_amount
        if job.partner_fee_amount and job.partner_fee_amount > 0
        else pl.partner_commission or 0.0
    )

    return render_template(
        "finance_payment_detail.html",
        placement=pl,
        candidate=cand,
        job=job,
        partner=partner,
        amount=amount,
    )


@finance_bp.route("/finance/payment-file/<int:placement_id>")
@login_required
def finance_payment_file(placement_id):
    """Скачать файл подтверждения выплаты партнёру.

    Доступен партнёру только по своим кандидатам,
    а также ролям coordinator/finance/director/admin/recruiter.
    """
    pl = db.session.get(Placement, placement_id)
    if not pl or not pl.partner_payment_file:
        abort(404)

    cand = db.session.get(Candidate, pl.candidate_id)
    if not cand:
        abort(404)

    # Проверка прав доступа
    if g.user.role == "partner":
        if cand.submitter_id != g.user.id:
            abort(403)
    elif g.user.role not in ("coordinator", "finance", "director", "admin", "recruiter"):
        abort(403)

    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "payments")
    final_path = os.path.join(upload_root, pl.partner_payment_file)
    if not os.path.exists(final_path):
        abort(404)

    directory, filename = os.path.split(final_path)
    return send_from_directory(directory, filename)


# ================================================================
#                   CONFIRM MONTH BY RECRUITER
# ================================================================
@finance_bp.post("/placement-confirm/<int:placement_id>")
@login_required
@roles_required("recruiter")
def placement_confirm(placement_id):
    placement = db.session.get(Placement, placement_id)
    if not placement:
        flash("Трудоустройство не найдено.", "danger")
        return redirect(url_for("main.index"))

    candidate = db.session.get(Candidate, placement.candidate_id)
    partner = db.session.get(User, candidate.submitter_id)

    if not partner or not partner.assigned_recruiter_id:
        flash("У партнёра нет назначенного рекрутёра.", "danger")
        return redirect(url_for("main.index"))

    if partner.assigned_recruiter_id != g.user.id:
        flash("Вы не можете подтвердить месяц по этому кандидату.", "danger")
        return redirect(url_for("main.index"))

    if placement.recruiter_confirmed:
        flash("Этот месяц уже подтверждён.", "info")
        return redirect(url_for("finance.confirm_month"))

    placement.recruiter_confirmed = True
    placement.recruiter_confirmed_at = datetime.utcnow()
    placement.recruiter_confirmed_by_id = g.user.id

    # Уведомление партнёру о том, что рекрутёр подтвердил месяц
    recipients = set()
    if partner and partner.id and partner.id != g.user.id:
        recipients.add(partner.id)
    if recipients:
        create_notification_for_users(
            recipients,
            f"Рекрутёр подтвердил месяц по кандидату {candidate.full_name}."
        )

    db.session.commit()
    flash("Месяц подтверждён!", "success")

    return redirect(url_for("finance.confirm_month"))


# ================================================================
#                       LIST TO CONFIRM
# ================================================================
@finance_bp.route("/confirm_month")
@login_required
@roles_required("recruiter")
def confirm_month():
    Partner = aliased(User)

    rows = (
        db.session.query(Placement, Candidate, Job)
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .join(Job, Job.id == Placement.job_id)
        .join(Partner, Partner.id == Candidate.submitter_id)
        .filter(
            Partner.assigned_recruiter_id == g.user.id,
            Placement.recruiter_confirmed == False,
        )
        .order_by(Placement.created_at.desc())
        .all()
    )

    return render_template("finance/confirm_month.html", rows=rows)

@finance_bp.route("/finance/history")
@login_required
@roles_required("coordinator", "finance")
def finance_history():
    """История выплат партнёрам с фильтрами по датам и партнёру."""
    today = date.today()
    default_from = today.replace(day=1).strftime("%Y-%m-%d")
    default_to = today.strftime("%Y-%m-%d")

    from_date = request.args.get("from_date") or default_from
    to_date = request.args.get("to_date") or default_to
    partner_id = request.args.get("partner_id", type=int)

    where_extra = ""
    params = {"from_date": from_date, "to_date": to_date}
    if partner_id:
        where_extra = " AND u.id = :partner_id"
        params["partner_id"] = partner_id

    sql = f"""
        SELECT 
          p.id AS placement_id,
          p.start_date AS start_date,
          p.partner_paid_at AS paid_at,
          c.full_name AS cand_name,
          j.title AS job_title,
          u.id AS partner_id,
          u.name AS partner_name,
          CASE 
            WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 THEN p.partner_commission
            WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 THEN 
              j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
            ELSE 0 
          END AS amount
        FROM placements p
        JOIN candidates c ON c.id = p.candidate_id
        JOIN jobs j ON j.id = p.job_id
        JOIN users u ON u.id = c.submitter_id
        WHERE p.partner_paid = 1
          AND p.partner_paid_at IS NOT NULL
          AND DATE(p.partner_paid_at) >= :from_date
          AND DATE(p.partner_paid_at) <= :to_date
          {where_extra}
        ORDER BY paid_at DESC, partner_name ASC
    """

    rows = db.session.execute(text(sql), params).mappings().all()

    partners = (
        db.session.query(User)
        .filter(User.role == "partner")
        .order_by(User.name.asc())
        .all()
    )

    per_partner = {}
    total_all = 0.0

    for r in rows:
        pid = r["partner_id"]
        entry = per_partner.setdefault(
            pid,
            {"partner_name": r["partner_name"], "total": 0.0, "count": 0},
        )
        entry["total"] += r["amount"] or 0.0
        entry["count"] += 1
        total_all += r["amount"] or 0.0

    return render_template(
        "finance_history.html",
        rows=rows,
        per_partner=per_partner,
        partners=partners,
        from_date=from_date,
        to_date=to_date,
        selected_partner_id=partner_id,
        total_all=total_all,
    )


@finance_bp.route("/finance/periods")
@login_required
@roles_required("coordinator", "finance", "admin")
def billing_periods():
    """Сводный список расчётных периодов для бухгалтера / координатора."""
    recruiter_alias = aliased(User)
    partner_alias = aliased(User)

    rows = (
        db.session.query(
            BillingPeriod,
            recruiter_alias.name.label("recruiter_name"),
            partner_alias.name.label("partner_name"),
        )
        .join(recruiter_alias, recruiter_alias.id == BillingPeriod.recruiter_id)
        .join(partner_alias, partner_alias.id == BillingPeriod.partner_id)
        .order_by(BillingPeriod.start_date.desc(), BillingPeriod.id.desc())
        .all()
    )
    return render_template("finance_periods.html", periods=rows)


@finance_bp.route("/finance/periods/<int:period_id>/set-status", methods=["POST"])
@login_required
@roles_required("coordinator", "finance", "admin")
def billing_period_set_status(period_id):
    period = db.session.get(BillingPeriod, period_id)
    if not period:
        abort(404)
    new_status = request.form.get("status")
    if new_status not in ("draft", "closed"):
        abort(400)
    period.status = new_status
    db.session.commit()
    flash("Статус расчётного периода обновлён.", "success")
    return redirect(url_for("finance.billing_periods"))