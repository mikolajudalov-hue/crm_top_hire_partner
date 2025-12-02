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
    CandidateStatusReason,
    create_notification_for_users,
)
from constants import PIPELINE
from auth_utils import login_required, roles_required

import os


candidates_bp = Blueprint('candidates', __name__)

@candidates_bp.route("/candidates")
@login_required
def candidates():
    job_id = request.args.get("job_id", type=int)
    recruiter_id = request.args.get("recruiter_id", type=int)
    partner_id = request.args.get("partner_id", type=int)
    status = request.args.get("status")
    min_fee = request.args.get("min_fee", type=float)
    max_fee = request.args.get("max_fee", type=float)

    from sqlalchemy import select
    partner_fee_base = (Job.partner_fee_amount * Job.promo_multiplier).label("partner_fee_base")

    q = (db.session.query(
         Candidate,
         case((Job.status=="active", Job.title), else_=None).label("job_title"),
         User.name.label("submitter_name"),
         User.note.label("submitter_note"),
         partner_fee_base,
         Candidate.partner_fee_offer.label("partner_fee_offer"),
         User.is_blocked.label("submitter_blocked"))
         .join(Job, Candidate.job_id==Job.id)
         .join(User, User.id==Candidate.submitter_id))

    if g.user.role=="partner":
        q = q.filter(Candidate.submitter_id==g.user.id)

    # Скрываем мягко удалённых кандидатов из списка
    q = q.filter(Candidate.status != "Удалён")

    if job_id:
        q = q.filter(Candidate.job_id==job_id)
    if recruiter_id is not None:
        sub = select(Placement.candidate_id).where(Placement.recruiter_id==recruiter_id)
        q = q.filter(Candidate.id.in_(sub))
    if partner_id is not None:
        q = q.filter(Candidate.submitter_id==partner_id)
    if status:
        q = q.filter(Candidate.status==status)
    if min_fee is not None:
        q = q.filter(Job.partner_fee_amount>=min_fee)
    if max_fee is not None:
        q = q.filter(Job.partner_fee_amount<=max_fee)

    rows = q.order_by(Candidate.created_at.desc()).limit(400).all()
    jobs = db.session.query(Job.id, Job.title).filter(Job.status=="active").order_by(Job.title.asc()).all()
    recruiters = db.session.query(User.id, User.name).filter(User.role=="recruiter").order_by(User.name.asc()).all()
    submitter_ids = {c.submitter_id for (c, *_) in rows}
    if submitter_ids:
        partners = db.session.query(User.id, User.name).filter(User.id.in_(submitter_ids)).order_by(User.name.asc()).all()
    else:
        partners = []

    unread_comments = {}
    if g.user:
        candidate_ids = [c.id for (c, *_) in rows]
        if candidate_ids:
            all_comments = db.session.query(CandidateComment).filter(CandidateComment.candidate_id.in_(candidate_ids)).all()
            seen_rows = db.session.query(CandidateCommentSeen).filter(
                CandidateCommentSeen.candidate_id.in_(candidate_ids),
                CandidateCommentSeen.user_id == g.user.id,
            ).all()
            seen_map = {s.candidate_id: s.last_seen_at for s in seen_rows}
            for cm in all_comments:
                last_seen = seen_map.get(cm.candidate_id)
                if (not last_seen) or (cm.created_at > last_seen):
                    unread_comments[cm.candidate_id] = unread_comments.get(cm.candidate_id, 0) + 1

    return render_template(
        "candidates.html",
        rows=rows,
        jobs=jobs,
        recruiters=recruiters,
        partners=partners,
        pipeline=PIPELINE,
        current={
            "job_id": job_id,
            "recruiter_id": recruiter_id,
            "partner_id": partner_id,
            "status": status,
            "min_fee": min_fee,
            "max_fee": max_fee,
        },
        unread_comments=unread_comments,
    )


@candidates_bp.route("/candidates/<int:cand_id>")
@login_required
def candidate_view(cand_id):
    c = (
        db.session.query(
            Candidate,
            case((Job.status == "active", Job.title), else_=None).label("job_title"),
            Job.partner_fee_amount.label("partner_fee_amount"),
            Job.recruiter_fee_amount.label("recruiter_fee_amount"),
            User.name.label("partner_name"),
            User.note.label("partner_note"),
            User.is_blocked.label("partner_blocked"),
        )
        .join(Job, Candidate.job_id == Job.id)
        .join(User, User.id == Candidate.submitter_id)
        .filter(Candidate.id == cand_id)
        .first()
    )
    if not c:
        abort(404)

    p = db.session.query(Placement).filter(Placement.candidate_id == cand_id).first()
    profile = db.session.query(CandidateProfile).filter(CandidateProfile.candidate_id == cand_id).first()
    cand_docs = (
        db.session.query(CandidateDoc)
        .filter(CandidateDoc.candidate_id == cand_id)
        .order_by(CandidateDoc.uploaded_at.desc())
        .all()
    )
    comments = (
        db.session.query(CandidateComment, User.name.label("author_name"))
        .join(User, User.id == CandidateComment.author_id)
        .filter(CandidateComment.candidate_id == cand_id)
        .order_by(CandidateComment.created_at.desc())
        .all()
    )

    status_reasons = (
        db.session.query(CandidateStatusReason)
        .filter(CandidateStatusReason.is_active == True)
        .order_by(CandidateStatusReason.sort_order, CandidateStatusReason.id)
        .all()
    )

    # Автоматический фолбэк: если причин ещё нет в БД (новая база),
    # создаём базовый набор причин и перечитываем.
    if not status_reasons:
        base_reasons = [
            dict(code="no_show_first_day",       title_ru="Не вышел в первый день",                         applies_to_status="Не вышел",    sort_order=10),
            dict(code="no_show_after_training",  title_ru="Не вышел после обучения / инструктажа",          applies_to_status="Не вышел",    sort_order=20),
            dict(code="refused_conditions",      title_ru="Отказался из-за условий работы",                 applies_to_status="Не вышел",    sort_order=30),
            dict(code="refused_salary",          title_ru="Отказался из-за зарплаты",                       applies_to_status="Не вышел",    sort_order=40),
            dict(code="personal_reasons",        title_ru="Личные обстоятельства (семья, здоровье)",        applies_to_status="Не вышел",    sort_order=50),
            dict(code="moved_to_another_job",    title_ru="Ушёл на другую работу",                          applies_to_status="Не отработал", sort_order=60),
            dict(code="low_performance",         title_ru="Низкая производительность / жалобы клиента",     applies_to_status="Не отработал", sort_order=70),
            dict(code="discipline_issues",       title_ru="Проблемы с дисциплиной (опоздания, прогулы)",    applies_to_status="Не отработал", sort_order=80),
            dict(code="housing_issues",          title_ru="Проблемы с жильём (условия, соседи)",            applies_to_status="Не вышел",    sort_order=90),
            dict(code="unknown_reason",          title_ru="Причина не уточнена",                            applies_to_status="",            sort_order=100),
        ]
        for idx, r in enumerate(base_reasons, start=1):
            db.session.add(
                CandidateStatusReason(
                    code=r["code"],
                    title_ru=r["title_ru"],
                    title_uk="",
                    applies_to_status=r.get("applies_to_status", ""),
                    sort_order=r.get("sort_order", idx * 10),
                    is_active=True,
                )
            )
        db.session.commit()
        status_reasons = (
            db.session.query(CandidateStatusReason)
            .filter(CandidateStatusReason.is_active == True)
            .order_by(CandidateStatusReason.sort_order, CandidateStatusReason.id)
            .all()
        )

    if g.user:
        seen = db.session.query(CandidateCommentSeen).filter_by(candidate_id=cand_id, user_id=g.user.id).first()
        now = datetime.utcnow()
        if not seen:
            seen = CandidateCommentSeen(candidate_id=cand_id, user_id=g.user.id, last_seen_at=now)
            db.session.add(seen)
        else:
            seen.last_seen_at = now
        db.session.commit()

    return render_template(
        "candidate_view.html",
        cand=c,
        placement=p,
        profile=profile,
        cand_docs=cand_docs,
        comments=comments,
        pipeline=PIPELINE,
        status_reasons=status_reasons,
    )

@candidates_bp.route("/candidates/<int:cand_id>/status", methods=["POST"])
@login_required
@roles_required("recruiter","coordinator")
def candidate_status(cand_id):
    new_status = request.form.get("status")
    if new_status not in PIPELINE:
        abort(400)

    c = db.session.get(Candidate, cand_id)
    if not c:
        abort(404)

    # Дополнительные поля для причины
    reason_id_val = request.form.get("status_reason_id")
    reason_comment = (request.form.get("status_reason_comment") or "").strip()
    reason = None
    if reason_id_val:
        try:
            rid = int(reason_id_val)
        except (TypeError, ValueError):
            rid = None
        if rid:
            reason = db.session.get(CandidateStatusReason, rid)

    old_status = c.status
    if old_status != new_status:
        c.status = new_status

        if reason:
            c.status_reason_id = reason.id
        else:
            c.status_reason_id = None
        c.status_reason_comment = reason_comment

        sys_text = f"Статус изменён с '{old_status}' на '{new_status}'"
        if reason:
            sys_text += f" | Причина: {reason.title_ru}"
        if reason_comment:
            sys_text += f" | Комментарий: {reason_comment}"

        db.session.add(
            CandidateComment(
                candidate_id=c.id,
                author_id=g.user.id,
                text=sys_text,
                created_at=datetime.utcnow(),
            )
        )
        db.session.add(
            CandidateLog(
                candidate_id=c.id,
                user_id=g.user.id,
                action="status_change",
                details=sys_text,
            )
        )

        recipients = set()
        if c.submitter_id and c.submitter_id != g.user.id:
            recipients.add(c.submitter_id)
        placement = db.session.query(Placement).filter_by(candidate_id=c.id).first()
        if placement and placement.recruiter_id and placement.recruiter_id != g.user.id:
            recipients.add(placement.recruiter_id)
        if recipients:
            create_notification_for_users(
                recipients,
                f"Статус кандидата {c.full_name} изменён с '{old_status}' на '{new_status}'",
            )
    db.session.commit()
    flash("Статус обновлён", "success")
    return redirect(url_for("candidates.candidate_view", cand_id=cand_id))


@candidates_bp.route("/candidates/<int:cand_id>/comment", methods=["POST"])
@login_required
def candidate_comment_add(cand_id):
    c = db.session.get(Candidate, cand_id)
    if not c:
        abort(404)
    text_val = (request.form.get("text") or "").strip()
    if not text_val:
        flash("Комментарий не может быть пустым.", "danger")
        return redirect(url_for("candidates.candidate_view", cand_id=cand_id))
    cm = CandidateComment(candidate_id=cand_id, author_id=g.user.id, text=text_val, created_at=datetime.utcnow())
    db.session.add(cm)
    # Лог о добавленном комментарии (первые 200 символов)
    log_details = (text_val[:200] + "...") if len(text_val) > 200 else text_val
    db.session.add(CandidateLog(candidate_id=c.id, user_id=g.user.id,
                               action="comment_add", details=log_details))

    # Уведомления: партнёр и рекрутёр по этому кандидату
    recipients = set()
    if c.submitter_id and c.submitter_id != g.user.id:
        recipients.add(c.submitter_id)

    placement = db.session.query(Placement).filter_by(candidate_id=c.id).first()
    if placement and placement.recruiter_id and placement.recruiter_id != g.user.id:
        recipients.add(placement.recruiter_id)

    if recipients:
        create_notification_for_users(
            recipients,
            f"Новый комментарий по кандидату {c.full_name}: {log_details}"
        )

    seen = db.session.query(CandidateCommentSeen).filter_by(candidate_id=cand_id, user_id=g.user.id).first()
    now = datetime.utcnow()
    if not seen:
        seen = CandidateCommentSeen(candidate_id=cand_id, user_id=g.user.id, last_seen_at=now)
        db.session.add(seen)
    else:
        seen.last_seen_at = now
    db.session.commit()
    flash("Комментарий добавлен.", "success")
    return redirect(url_for("candidates.candidate_view", cand_id=cand_id))


@candidates_bp.route("/candidates/<int:cand_id>/start", methods=["POST"])
@login_required
@roles_required("recruiter","coordinator")
def candidate_start(cand_id):
    c = db.session.get(Candidate, cand_id)
    if not c: abort(404)
    start_date = request.form.get("start_date")
    pc = float(request.form.get("partner_commission") or 0)
    rc = float(request.form.get("recruiter_commission") or 0)
    p = db.session.query(Placement).filter(Placement.candidate_id==cand_id).first()
    profile = db.session.query(CandidateProfile).filter(CandidateProfile.candidate_id==cand_id).first()
    cand_docs = (db.session.query(CandidateDoc)
        .filter(CandidateDoc.candidate_id==cand_id)
        .order_by(CandidateDoc.uploaded_at.desc())
        .all())
    if not p:
        p = Placement(candidate_id=c.id, job_id=c.job_id, recruiter_id=g.user.id,
                      start_date=start_date, partner_commission=pc, recruiter_commission=rc, status="Вышел на работу")
        db.session.add(p)
    else:
        p.start_date = start_date
        p.partner_commission = pc
        p.recruiter_commission = rc
        p.recruiter_id = g.user.id
    c.status = "Вышел на работу"

    # Уведомления о выходе кандидата на работу
    recipients = set()
    # Партнёр-отправитель
    if c.submitter_id and c.submitter_id != g.user.id:
        recipients.add(c.submitter_id)
    # Рекрутёр назначения
    if p.recruiter_id and p.recruiter_id != g.user.id:
        recipients.add(p.recruiter_id)
    if recipients:
        create_notification_for_users(
            recipients,
            f"Кандидат {c.full_name} вышел на работу ({start_date})"
        )

    db.session.commit()
    flash("Первый рабочий день зафиксирован", "success")
    return redirect(url_for("candidates.candidate_view", cand_id=cand_id))


@candidates_bp.route("/candidates/<int:cand_id>/delete", methods=["POST"])
@login_required
@roles_required("coordinator")
def candidate_delete(cand_id):
    c = db.session.get(Candidate, cand_id)
    if not c:
        abort(404)

    # Мягкое удаление: помечаем кандидата как удалённого и пишем лог
    old_status = c.status
    c.status = "Удалён"
    db.session.add(CandidateLog(candidate_id=c.id, user_id=g.user.id,
                               action="candidate_deleted",
                               details=f"Удалён кандидатором со статусом '{old_status}'"))

    # Уведомления об удалении кандидата
    recipients = set()
    if c.submitter_id and c.submitter_id != g.user.id:
        recipients.add(c.submitter_id)
    placement = db.session.query(Placement).filter_by(candidate_id=c.id).first()
    if placement and placement.recruiter_id and placement.recruiter_id != g.user.id:
        recipients.add(placement.recruiter_id)
    if recipients:
        create_notification_for_users(
            recipients,
            f"Кандидат {c.full_name} помечен как удалён (старый статус: '{old_status}')"
        )

    db.session.commit()
    flash("Кандидат помечен как удалён.", "success")
    return redirect(url_for("candidates.candidates"))


@candidates_bp.route("/candidate-doc/<int:doc_id>")
@login_required
def candidate_doc(doc_id):
    d = db.session.get(CandidateDoc, doc_id)
    if not d:
        abort(404)
    c = db.session.get(Candidate, d.candidate_id)
    if not c:
        abort(404)
    # Права: партнёр может смотреть только своих кандидатов,
    # рекрутер/координатор/финансы могут смотреть всех.
    if g.user.role == "partner":
        if c.submitter_id != g.user.id:
            abort(403)
    elif g.user.role not in ("recruiter", "coordinator", "director", "finance"):
        abort(403)

    # Базовая папка для документов кандидатов
    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "candidate_docs")

    # Возможные варианты расположения файла:
    #  1) как сейчас сохраняется: "<candidate_id>/<file>"
    #  2) только имя файла внутри папки кандидата
    candidates = []

    # Вариант 1: как записано в базе (может уже содержать подкаталог)
    if d.filename:
        candidates.append(os.path.join(upload_root, d.filename))

    # Вариант 2: файл лежит в подпапке с id кандидата,
    # а в базе хранится только имя файла.
    if d.filename and os.sep not in d.filename and "/" not in d.filename:
        candidates.append(os.path.join(upload_root, str(d.candidate_id), d.filename))

    # Вариант 3: если путь не найден, но в папке кандидата ровно один файл — пробуем его.
    cand_dir = os.path.join(upload_root, str(d.candidate_id))
    try:
        if os.path.isdir(cand_dir):
            files = [f for f in os.listdir(cand_dir) if os.path.isfile(os.path.join(cand_dir, f))]
            if len(files) == 1:
                candidates.append(os.path.join(cand_dir, files[0]))
    except OSError:
        pass

    final_path = None
    for path in candidates:
        if path and os.path.exists(path):
            final_path = path
            break

    if not final_path:
        flash("Файл документа не найден на сервере.", "danger")
        return redirect(url_for("candidates.candidate_view", cand_id=c.id))

    directory, filename = os.path.split(final_path)
    return send_from_directory(directory, filename)