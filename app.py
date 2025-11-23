from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for, session, g, abort, flash, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Job, Candidate, Placement, BillingPeriod, PartnerDoc, CandidateComment, CandidateCommentSeen, CandidateLog, CandidateProfile, CandidateDoc, init_db, get_engine
from models import News, NewsRead
import os
from sqlalchemy import func, text, case
from sqlalchemy.orm import aliased

BRAND = "TopHire Business CRM"

LANG_CHOICES = ["ru", "uk"]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")
engine = get_engine()
db.configure(bind=engine)

PORT = int(os.environ.get("PORT", "8107"))
PIPELINE = ["Подан","Вышел на работу","Не вышел","Отработал месяц","Не отработал"]

@app.context_processor
def inject_brand():
    lang = session.get("lang", "ru")
    return {"BRAND": BRAND, "current_lang": lang}

@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db.session.get(User, uid)
    g.inbox_count = 0
    g.news_unread_count = 0
    if g.user and g.user.role in ("recruiter","coordinator"):
        g.inbox_count = db.session.query(func.count(Candidate.id)).filter(Candidate.status=="Подан").scalar() or 0
    if g.user:
        g.news_unread_count = (
            db.session.query(func.count(News.id))
            .outerjoin(NewsRead, (NewsRead.news_id == News.id) & (NewsRead.user_id == g.user.id))
            .filter(News.is_published == True, NewsRead.id.is_(None))
            .scalar()
            or 0
        )

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper

def roles_required(*roles):
    from functools import wraps
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if not g.user or g.user.role not in roles:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.session.query(User).filter(User.email==email, User.is_active==True).first()
        if not user or not check_password_hash(user.password_hash, password):
            return render_template("login.html", error="Неверные данные")
        session["uid"] = user.id
        return redirect(url_for("index"))
    return render_template("login.html", error=None)

@app.route("/set-lang/<lang>")
@login_required
def set_lang(lang):
    if lang not in LANG_CHOICES:
        abort(404)
    session["lang"] = lang
    next_url = request.args.get("next") or request.referrer or url_for("index")
    return redirect(next_url)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
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
            func.strftime("%Y-%m", Candidate.created_at)==ym,
            Candidate.status != "Удалён").scalar() or 0

        my_starts = (db.session.query(func.count(Placement.id))
                     .join(Candidate, Candidate.id==Placement.candidate_id)
                     .filter(Candidate.submitter_id==u.id,
                             func.strftime("%Y-%m", Placement.start_date)==ym).scalar() or 0)

        # Начислено за месяц
        my_month_accrued = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                             .join(Candidate, Candidate.id==Placement.candidate_id)
                             .filter(Candidate.submitter_id==u.id,
                                     func.strftime("%Y-%m", Placement.start_date)==ym).scalar() or 0.0)

        # Выплачено за месяц
        my_month_paid = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                          .join(Candidate, Candidate.id==Placement.candidate_id)
                          .filter(Candidate.submitter_id==u.id,
                                  Placement.partner_paid == True,
                                  Placement.partner_paid_at.is_not(None),
                                  func.strftime("%Y-%m", Placement.partner_paid_at)==ym).scalar() or 0.0)

        # Общий баланс: начислено минус выплачено (за всё время)
        total_accrued = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                          .join(Candidate, Candidate.id==Placement.candidate_id)
                          .filter(Candidate.submitter_id==u.id).scalar() or 0.0)
        total_paid = (db.session.query(func.coalesce(func.sum(Placement.partner_commission), 0.0))
                       .join(Candidate, Candidate.id==Placement.candidate_id)
                       .filter(Candidate.submitter_id==u.id,
                               Placement.partner_paid == True).scalar() or 0.0)
        my_balance = total_accrued - total_paid

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
            func.strftime("%Y-%m", Placement.start_date)==ym).scalar() or 0
        month_submissions = db.session.query(func.count(Candidate.id)).filter(
            func.strftime("%Y-%m", Candidate.created_at)==ym).scalar() or 0
        partner_sum = db.session.query(func.coalesce(func.sum(Placement.partner_commission),0.0)).filter(
            func.strftime("%Y-%m", Placement.start_date)==ym).scalar() or 0.0
        recruiter_sum = db.session.query(func.coalesce(func.sum(Placement.recruiter_commission),0.0)).filter(
            func.strftime("%Y-%m", Placement.start_date)==ym).scalar() or 0.0

        top_rec = db.session.execute(text("""
            SELECT u.name as name, COUNT(p.id) as starts, COALESCE(SUM(p.recruiter_commission),0) as recruiter_sum
            FROM placements p
            JOIN users u ON u.id = p.recruiter_id
            WHERE strftime('%Y-%m', p.start_date) = :ym
            GROUP BY u.id ORDER BY starts DESC LIMIT 10
        """), {"ym": ym}).mappings().all()

        top_par = db.session.execute(text("""
            SELECT u.name as name, COUNT(p.id) as starts, COALESCE(SUM(p.partner_commission),0) as partner_sum
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN users u ON u.id = c.submitter_id
            WHERE strftime('%Y-%m', p.start_date) = :ym
            GROUP BY u.id ORDER BY starts DESC LIMIT 10
        """), {"ym": ym}).mappings().all()

        return render_template("dash_staff.html", submissions=submissions, placements=placements,
                               kpi={"month_starts": month_starts,
                                    "month_submissions": month_submissions,
                                    "month_partner_sum": round(partner_sum,2),
                                    "month_recruiter_sum": round(recruiter_sum,2),
                                    "by_recruiter": top_rec, "by_partner": top_par})

@app.route("/inbox")
@login_required
def inbox():
    if g.user.role not in ("recruiter","coordinator"):
        return redirect(url_for("index"))
    rows = (db.session.query(Candidate, case((Job.status=="active", Job.title), else_=None).label("job_title"), User.name.label("submitter_name"), User.note.label("submitter_note"))
            .join(Job, Candidate.job_id==Job.id)
            .join(User, User.id==Candidate.submitter_id)
            .filter(Candidate.status=="Подан")
            .order_by(Candidate.created_at.desc()).limit(300).all())
    return render_template("inbox.html", rows=rows)


@app.route("/jobs")
@login_required
def jobs():
    # Для списка вакансий показываем все, кроме удалённых.
    # "Не актуальные" (status == "inactive") всегда внизу списка.
    jobs = (
        db.session.query(Job)
        .filter(Job.status != "deleted")
        .order_by(
            case(
                (Job.status == "active", 0),
                (Job.status == "inactive", 1),
                else_=2,
            ),
            case(
                (Job.priority == "top", 0),
                (Job.priority == "urgent", 1),
                (Job.priority == "normal", 2),
                else_=3,
            ),
            Job.created_at.desc(),
        )
        .limit(200)
        .all()
    )
    return render_template("jobs.html", jobs=jobs)
@app.route("/jobs/<int:job_id>/pin", methods=["POST"])
@login_required
@roles_required("coordinator", "recruiter")
def job_pin(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)
    # toggle top priority
    if j.priority == "top":
        j.priority = "normal"
    else:
        j.priority = "top"
    db.session.commit()
    return redirect(url_for("jobs"))

@app.route("/jobs/new", methods=["GET","POST"])
@login_required
@roles_required("coordinator")
def job_new():
    if request.method == "POST":
        gender_pref = (request.form.get("gender_preference") or "").strip()
        age_to_raw = (request.form.get("age_to") or "").strip()
        try:
            age_to_val = int(age_to_raw) if age_to_raw else 0
        except ValueError:
            age_to_val = 0

        j = Job(
            title=request.form.get("title"," ").strip(),
            location=request.form.get("location"," ").strip(),
            description=request.form.get("description"," ").strip(),
            short_description=(request.form.get("short_description") or "").strip(),
            priority=request.form.get("priority","normal"),
            gender_preference=gender_pref,
            age_to=age_to_val,
            partner_fee_amount=float(request.form.get("partner_fee_amount") or 0),
            recruiter_fee_amount=float(request.form.get("recruiter_fee_amount") or 0),
            promo_multiplier=float(request.form.get("promo_multiplier") or 1.0),
            promo_label=(request.form.get("promo_label") or "").strip(),
            status="active"
        )
        db.session.add(j)
        db.session.commit()
        flash("Вакансия создана", "success")
        return redirect(url_for("jobs"))
    return render_template("job_new.html")

@app.route("/jobs/<int:job_id>")
@login_required
def job_view(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)
    return render_template("job_view.html", job=j)

@app.route("/jobs/<int:job_id>/promo", methods=["POST"])
@login_required
@roles_required("coordinator")
def job_promo_update(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)
    j.promo_multiplier = float(request.form.get("promo_multiplier") or 1.0)
    j.promo_label = (request.form.get("promo_label") or "").strip()
    db.session.commit()
    flash("Акция по вакансии обновлена", "success")
    return redirect(url_for("job_view", job_id=job_id))

@app.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
@roles_required("coordinator")
def job_delete(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)

    # Мягкое удаление: помечаем вакансию как удалённую, кандидатов не трогаем
    j.status = "deleted"
    j.priority = "low"

    db.session.commit()
    flash("Вакансия помечена как удалённая. Кандидаты сохранены.", "success")
    return redirect(url_for("jobs"))



@app.route("/jobs/<int:job_id>/edit", methods=["GET","POST"])
@login_required
@roles_required("coordinator", "recruiter")
def job_edit(job_id):
    j = db.session.get(Job, job_id)
    if not j or j.status == "deleted":
        abort(404)

    if request.method == "POST":
        j.title = (request.form.get("title") or "").strip()
        j.location = (request.form.get("location") or "").strip()
        j.description = (request.form.get("description") or "").strip()
        j.short_description = (request.form.get("short_description") or "").strip()
        j.priority = request.form.get("priority") or "normal"

        j.gender_preference = (request.form.get("gender_preference") or "").strip()
        age_to_raw = (request.form.get("age_to") or "").strip()
        try:
            j.age_to = int(age_to_raw) if age_to_raw else 0
        except ValueError:
            j.age_to = 0

        j.partner_fee_amount = float(request.form.get("partner_fee_amount") or 0)
        j.recruiter_fee_amount = float(request.form.get("recruiter_fee_amount") or 0)
        j.promo_multiplier = float(request.form.get("promo_multiplier") or 1.0)
        j.promo_label = (request.form.get("promo_label") or "").strip()

        status = (request.form.get("status") or "active").strip()
        if status not in ("active", "inactive"):
            status = "active"
        j.status = status

        db.session.commit()
        flash("Вакансия обновлена", "success")
        return redirect(url_for("job_view", job_id=j.id))

    return render_template("job_edit.html", job=j)

@app.route("/jobs/<int:job_id>/submit", methods=["GET","POST"])
@login_required
def job_submit(job_id):
    j = db.session.get(Job, job_id)
    if not j or j.status!="active": abort(404)
    # Блокировка подачи от запрещённых партнёров
    if g.user.role == "partner" and g.user.is_blocked:
        flash("Ваш аккаунт помечен как ограниченный: подача кандидатов недоступна. Обратитесь к координатору.", "danger")
        return redirect(url_for("index"))
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        has_driver_license = (request.form.get("has_driver_license") == "yes")
        work_experience = (request.form.get("work_experience") or "").strip()
        age_raw = (request.form.get("age") or "").strip()
        age_val = None
        if age_raw:
            try:
                age_val = int(age_raw)
            except ValueError:
                age_val = None
        has_work_shoes = (request.form.get("has_work_shoes") == "yes")
        planned_arrival_str = (request.form.get("planned_arrival") or "").strip()
        planned_arrival = None
        if planned_arrival_str:
            try:
                planned_arrival = datetime.strptime(planned_arrival_str, "%Y-%m-%d")
            except ValueError:
                planned_arrival = None
        citizenship = (request.form.get("citizenship") or "").strip()

        # Фиксируем комиссию на момент подачи (с учётом текущего бустера)
        partner_offer = (j.partner_fee_amount or 0.0) * (j.promo_multiplier or 1.0)
        recruiter_offer = j.recruiter_fee_amount or 0.0

        c = Candidate(
            job_id = j.id,
            submitter_id = g.user.id,
            full_name = full_name,
            phone = phone,
            email = "",
            cv_url = "",
            notes = "",
            status = "Подан",
            partner_fee_offer = partner_offer,
            recruiter_fee_offer = recruiter_offer,
            created_at = datetime.utcnow()
        )
        db.session.add(c)
        db.session.flush()

        profile = CandidateProfile(
            candidate_id=c.id,
            has_driver_license=has_driver_license,
            work_experience=work_experience,
            age=age_val,
            has_work_shoes=has_work_shoes,
            planned_arrival=planned_arrival,
            citizenship=citizenship,
        )
        db.session.add(profile)

        file = request.files.get("doc_file")
        if file and file.filename:
            upload_root = os.path.join(os.path.dirname(__file__), "uploads", "candidate_docs")
            os.makedirs(upload_root, exist_ok=True)
            safe_name = secure_filename(file.filename)
            cand_dir = os.path.join(upload_root, str(c.id))
            os.makedirs(cand_dir, exist_ok=True)
            rel_name = os.path.join(str(c.id), safe_name)
            save_path = os.path.join(upload_root, rel_name)
            file.save(save_path)
            db.session.add(CandidateDoc(candidate_id=c.id, filename=rel_name, label="Документ"))

        db.session.commit()
        flash(f"Кандидат «{c.full_name}» отправлен на вакансию «{j.title}».", "success")
        if g.user.role in ("recruiter","coordinator"):
            return redirect(url_for("inbox"))
        return redirect(url_for("index"))
    return render_template("candidate_submit.html", job=j)

@app.route("/candidates")
@login_required
def candidates():
    job_id = request.args.get("job_id", type=int)
    recruiter_id = request.args.get("recruiter_id", type=int)
    status = request.args.get("status")
    min_fee = request.args.get("min_fee", type=float)
    max_fee = request.args.get("max_fee", type=float)

    from sqlalchemy import select
    q = (db.session.query(Candidate,
         case((Job.status=="active", Job.title), else_=None).label("job_title"),
         User.name.label("submitter_name"),
         User.note.label("submitter_note"),
         Job.partner_fee_amount.label("partner_fee"),
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
    if status:
        q = q.filter(Candidate.status==status)
    if min_fee is not None:
        q = q.filter(Job.partner_fee_amount>=min_fee)
    if max_fee is not None:
        q = q.filter(Job.partner_fee_amount<=max_fee)

    rows = q.order_by(Candidate.created_at.desc()).limit(400).all()
    jobs = db.session.query(Job.id, Job.title).filter(Job.status=="active").order_by(Job.title.asc()).all()
    recruiters = db.session.query(User.id, User.name).filter(User.role=="recruiter").order_by(User.name.asc()).all()

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

    return render_template("candidates.html", rows=rows, jobs=jobs, recruiters=recruiters, pipeline=PIPELINE,
                           current={"job_id":job_id,"recruiter_id":recruiter_id,"status":status,"min_fee":min_fee,"max_fee":max_fee},
                           unread_comments=unread_comments)

@app.route("/candidates/<int:cand_id>")
@login_required
def candidate_view(cand_id):
    c = (db.session.query(Candidate,
        case((Job.status=="active", Job.title), else_=None).label("job_title"),
        Job.partner_fee_amount.label("partner_fee_amount"),
        Job.recruiter_fee_amount.label("recruiter_fee_amount"),
        User.name.label("partner_name"),
        User.note.label("partner_note"),
        User.is_blocked.label("partner_blocked"))
        .join(Job, Candidate.job_id==Job.id)
        .join(User, User.id==Candidate.submitter_id)
        .filter(Candidate.id==cand_id)
        .first())
    if not c: abort(404)
    p = db.session.query(Placement).filter(Placement.candidate_id==cand_id).first()
    profile = db.session.query(CandidateProfile).filter(CandidateProfile.candidate_id==cand_id).first()
    cand_docs = (db.session.query(CandidateDoc)
        .filter(CandidateDoc.candidate_id==cand_id)
        .order_by(CandidateDoc.uploaded_at.desc())
        .all())
    comments = (db.session.query(CandidateComment, User.name.label("author_name"))
        .join(User, User.id==CandidateComment.author_id)
        .filter(CandidateComment.candidate_id==cand_id)
        .order_by(CandidateComment.created_at.asc())
        .all())

    if g.user:
        seen = db.session.query(CandidateCommentSeen).filter_by(candidate_id=cand_id, user_id=g.user.id).first()
        now = datetime.utcnow()
        if not seen:
            seen = CandidateCommentSeen(candidate_id=cand_id, user_id=g.user.id, last_seen_at=now)
            db.session.add(seen)
        else:
            seen.last_seen_at = now
        db.session.commit()

    return render_template("candidate_view.html", cand=c, placement=p, pipeline=PIPELINE, comments=comments, profile=profile, cand_docs=cand_docs)

@app.route("/candidates/<int:cand_id>/status", methods=["POST"])
@login_required
@roles_required("recruiter","coordinator")
def candidate_status(cand_id):
    new_status = request.form.get("status")
    if new_status not in PIPELINE:
        abort(400)
    c = db.session.get(Candidate, cand_id)
    if not c: abort(404)
    old_status = c.status
    if old_status != new_status:
        c.status = new_status
        # Системный комментарий о смене статуса
        sys_text = f"Статус изменён с '{old_status}' на '{new_status}'"
        db.session.add(CandidateComment(candidate_id=c.id, author_id=g.user.id,
                                        text=sys_text, created_at=datetime.utcnow()))
        # Лог изменения статуса
        db.session.add(CandidateLog(candidate_id=c.id, user_id=g.user.id,
                                   action="status_change", details=sys_text))
    db.session.commit()
    flash("Статус обновлён", "success")
    return redirect(url_for("candidate_view", cand_id=cand_id))

@app.route("/candidates/<int:cand_id>/comment", methods=["POST"])
@login_required
def candidate_comment_add(cand_id):
    c = db.session.get(Candidate, cand_id)
    if not c:
        abort(404)
    text_val = (request.form.get("text") or "").strip()
    if not text_val:
        flash("Комментарий не может быть пустым.", "danger")
        return redirect(url_for("candidate_view", cand_id=cand_id))
    cm = CandidateComment(candidate_id=cand_id, author_id=g.user.id, text=text_val, created_at=datetime.utcnow())
    db.session.add(cm)
    # Лог о добавленном комментарии (первые 200 символов)
    log_details = (text_val[:200] + "...") if len(text_val) > 200 else text_val
    db.session.add(CandidateLog(candidate_id=c.id, user_id=g.user.id,
                               action="comment_add", details=log_details))
    seen = db.session.query(CandidateCommentSeen).filter_by(candidate_id=cand_id, user_id=g.user.id).first()
    now = datetime.utcnow()
    if not seen:
        seen = CandidateCommentSeen(candidate_id=cand_id, user_id=g.user.id, last_seen_at=now)
        db.session.add(seen)
    else:
        seen.last_seen_at = now
    db.session.commit()
    flash("Комментарий добавлен.", "success")
    return redirect(url_for("candidate_view", cand_id=cand_id))

@app.route("/candidates/<int:cand_id>/start", methods=["POST"])
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
    db.session.commit()
    flash("Первый рабочий день зафиксирован", "success")
    return redirect(url_for("candidate_view", cand_id=cand_id))

@app.route("/candidates/<int:cand_id>/delete", methods=["POST"])
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
    db.session.commit()
    flash("Кандидат помечен как удалён.", "success")
    return redirect(url_for("candidates"))

@app.route("/reports")
@login_required
@roles_required("recruiter","coordinator")
def reports():
    ym = request.args.get("month") or date.today().strftime("%Y-%m")
    rows = (db.session.query(Placement,
            Candidate.full_name.label("cand_name"),
            Job.title.label("job_title"),
            db.session.query(User.name).filter(User.id==Candidate.submitter_id).correlate(Candidate).scalar_subquery().label("partner_name"),
            User.name.label("recruiter_name"))
            .join(Candidate, Candidate.id==Placement.candidate_id)
            .join(Job, Job.id==Placement.job_id)
            .join(User, User.id==Placement.recruiter_id)
            .filter(func.strftime("%Y-%m", Placement.start_date)==ym)
            .order_by(Placement.start_date.asc()).all())
    return render_template("reports.html", rows=rows, ym=ym)



# ---------- FINANCE & PARTNER MODULE ----------

@app.route("/finance")
@login_required
@roles_required("coordinator", "finance")
def finance_dashboard():
    total_periods = db.session.query(func.count(BillingPeriod.id)).scalar() or 0
    total_amount = db.session.query(func.coalesce(func.sum(BillingPeriod.total_amount), 0.0)).scalar() or 0.0
    total_placements = db.session.query(func.count(Placement.id)).scalar() or 0
    return render_template(
        "finance_dashboard.html",
        total_periods=total_periods,
        total_amount=round(total_amount, 2),
        total_placements=total_placements,
    )


@app.route("/finance/partners")
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
                       WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 THEN p.partner_commission
                       WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 THEN j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
                       ELSE 0 END
                   ), 0) AS total
            FROM placements p
            JOIN candidates c ON c.id = p.candidate_id
            JOIN jobs j ON j.id = p.job_id
            GROUP BY c.submitter_id
            """
        )
    ).mappings().all()
    stat_map = {row["pid"]: row for row in rows}
    return render_template("finance_partners.html", partners=partners, stat_map=stat_map)


@app.route("/finance/partners/<int:pid>")
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
        {"pid": pid},
    ).mappings().all()
    total_all = sum(r["total"] for r in rows) if rows else 0.0

    return render_template(
        "finance_partner_view.html",
        partner=partner,
        docs=docs,
        rows=rows,
        total_all=total_all,
    )


@app.route("/finance/payments")
@login_required
@roles_required("coordinator", "finance")
def finance_payments():
    as_of = request.args.get("as_of") or date.today().strftime("%Y-%m-%d")

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
              CASE 
                WHEN p.partner_commission IS NOT NULL AND p.partner_commission > 0 THEN p.partner_commission
                WHEN j.partner_fee_amount IS NOT NULL AND j.partner_fee_amount > 0 THEN 
                  j.partner_fee_amount * COALESCE(j.promo_multiplier, 1)
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

    per_partner = {}
    for r in rows:
        pid = r["partner_id"]
        entry = per_partner.setdefault(
            pid,
            {"partner_name": r["partner_name"], "total": 0.0, "count": 0},
        )
        entry["total"] += r["amount"]
        entry["count"] += 1

    return render_template(
        "finance_payments.html",
        rows=rows,
        per_partner=per_partner,
        as_of=as_of,
    )


@app.route("/finance/payments/<int:placement_id>", methods=["GET", "POST"])
@login_required
@roles_required("coordinator", "finance")
def finance_payment_detail(placement_id):
    pl = db.session.get(Placement, placement_id)
    if not pl:
        abort(404)
    cand = db.session.get(Candidate, pl.candidate_id)
    job = db.session.get(Job, pl.job_id)
    partner = None
    if cand:
        partner = db.session.get(User, cand.submitter_id)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "mark_paid":
            file = request.files.get("payment_file")
            filename = pl.partner_payment_file or ""
            if file and file.filename:
                pay_root = os.path.join(os.path.dirname(__file__), "uploads", "payments")
                os.makedirs(pay_root, exist_ok=True)
                safe_name = secure_filename(file.filename)
                save_path = os.path.join(pay_root, f"pl_{placement_id}_{safe_name}")
                file.save(save_path)
                filename = os.path.basename(save_path)
            pl.partner_paid = True
            pl.partner_paid_at = datetime.utcnow()
            pl.partner_payment_file = filename
            db.session.commit()
            flash("Выплата отмечена как оплаченная", "success")
            return redirect(url_for("finance_payments"))

    if job:
        amount = (
            job.partner_fee_amount
            if job.partner_fee_amount and job.partner_fee_amount > 0
            else pl.partner_commission or 0.0
        )
    else:
        amount = pl.partner_commission or 0.0

    return render_template(
        "finance_payment_detail.html",
        placement=pl,
        candidate=cand,
        job=job,
        partner=partner,
        amount=amount,
    )


@app.route("/finance/periods")
@login_required
@roles_required("coordinator", "finance")
def finance_periods():
    Recruiter = aliased(User)
    PartnerUser = aliased(User)
    periods = (
        db.session.query(
            BillingPeriod,
            Recruiter.name.label("recruiter_name"),
            Recruiter.email.label("recruiter_email"),
            PartnerUser.name.label("partner_name"),
        )
        .join(Recruiter, Recruiter.id == BillingPeriod.recruiter_id)
        .join(PartnerUser, PartnerUser.id == BillingPeriod.partner_id)
        .order_by(BillingPeriod.created_at.desc())
        .all()
    )
    return render_template("finance_periods.html", periods=periods)


@app.route("/finance/periods/create", methods=["GET", "POST"])
@login_required
@roles_required("coordinator", "finance")
def finance_create_period():
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

    if request.method == "POST":
        recruiter_id = int(request.form.get("recruiter_id") or 0)
        partner_id = int(request.form.get("partner_id") or 0)
        start_date = (request.form.get("start_date") or "").strip()
        end_date = (request.form.get("end_date") or "").strip()
        if not (recruiter_id and partner_id and start_date and end_date):
            flash("Заполните все поля", "danger")
        else:
            q = (
                db.session.query(Placement, Candidate, Job)
                .join(Candidate, Candidate.id == Placement.candidate_id)
                .join(Job, Job.id == Placement.job_id)
                .filter(Placement.recruiter_id == recruiter_id)
                .filter(Candidate.submitter_id == partner_id)
                .filter(Placement.start_date >= start_date, Placement.start_date <= end_date)
            )
            rows = q.all()
            placements_count = len(rows)
            total_amount = 0.0
            for pl, cand, job in rows:
                amount = job.partner_fee_amount or pl.partner_commission or 0.0
                total_amount += amount

            period = BillingPeriod(
                recruiter_id=recruiter_id,
                partner_id=partner_id,
                start_date=start_date,
                end_date=end_date,
                placements_count=placements_count,
                total_amount=total_amount,
            )
            db.session.add(period)
            db.session.commit()
            flash(
                f"Период создан, найдено {placements_count} кандидатов, сумма {round(total_amount, 2)}",
                "success",
            )
            return redirect(url_for("finance_periods"))

    return render_template(
        "finance_create_period.html",
        recruiters=recruiters,
        partners=partners,
    )


@app.route("/finance/periods/<int:pid>", methods=["GET", "POST"])
@login_required
@roles_required("coordinator", "finance")
def finance_period_view(pid):
    period = db.session.get(BillingPeriod, pid)
    if not period:
        abort(404)

    Recruiter = aliased(User)
    PartnerUser = aliased(User)

    q = (
        db.session.query(
            Placement,
            Candidate.full_name.label("cand_name"),
            Job.title.label("job_title"),
            Recruiter.name.label("recruiter_name"),
            PartnerUser.name.label("partner_name"),
            Job.partner_fee_amount.label("partner_fee"),
            Placement.partner_commission.label("partner_commission"),
            Placement.start_date.label("start_date"),
        )
        .join(Candidate, Candidate.id == Placement.candidate_id)
        .join(Job, Job.id == Placement.job_id)
        .join(Recruiter, Recruiter.id == Placement.recruiter_id)
        .join(PartnerUser, PartnerUser.id == Candidate.submitter_id)
        .filter(Placement.recruiter_id == period.recruiter_id)
        .filter(Candidate.submitter_id == period.partner_id)
        .filter(
            Placement.start_date >= period.start_date,
            Placement.start_date <= period.end_date,
        )
        .order_by(Placement.start_date.asc())
    )

    rows = q.all()
    items = []
    total_amount = 0.0
    for (
        pl,
        cand_name,
        job_title,
        recruiter_name,
        partner_name,
        partner_fee,
        partner_commission,
        start_date,
    ) in rows:
        amount = partner_fee or partner_commission or 0.0
        total_amount += amount
        items.append(
            {
                "placement": pl,
                "cand_name": cand_name,
                "job_title": job_title,
                "recruiter_name": recruiter_name,
                "partner_name": partner_name,
                "amount": amount,
                "start_date": start_date,
            }
        )

    if request.method == "POST":
        file = request.files.get("invoice")
        if file and file.filename:
            invoices_dir = os.path.join(os.path.dirname(__file__), "uploads", "invoices")
            os.makedirs(invoices_dir, exist_ok=True)
            safe_name = secure_filename(file.filename)
            save_path = os.path.join(invoices_dir, f"period_{pid}_{safe_name}")
            file.save(save_path)
            period.invoice_filename = os.path.basename(save_path)
            period.total_amount = total_amount
            period.placements_count = len(items)
            db.session.commit()
            flash("Фактура загружена", "success")
            return redirect(url_for("finance_period_view", pid=pid))

    return render_template(
        "finance_period_view.html",
        period=period,
        items=items,
        total_amount=round(total_amount, 2),
    )


@app.route("/partner/profile", methods=["GET", "POST"])
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
        return redirect(url_for("partner_profile"))

    docs = (
        db.session.query(PartnerDoc)
        .filter(PartnerDoc.partner_id == g.user.id)
        .order_by(PartnerDoc.uploaded_at.desc())
        .all()
    )
    return render_template("partner_profile.html", user=u, docs=docs)


@app.route("/candidate-doc/<int:doc_id>")
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
    elif g.user.role not in ("recruiter", "coordinator", "finance"):
        abort(403)
    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "candidate_docs")
    full_path = os.path.join(upload_root, d.filename)
    if not os.path.exists(full_path):
        flash("Файл документа не найден на сервере.", "danger")
        return redirect(url_for("candidate_view", cand_id=c.id))
    # d.filename может содержать подкаталог вида "<id>/<file>", send_from_directory это поддерживает
    return send_from_directory(upload_root, d.filename)

@app.route("/partner-doc/<int:doc_id>")
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
    elif g.user.role not in ("coordinator", "finance"):
        abort(403)

    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "partner_docs")
    return send_from_directory(upload_root, d.filename)

@app.route("/partner/earnings")
@login_required
@roles_required("partner")
def partner_earnings():
    u = g.user
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
    total_all = sum(r["total"] for r in rows) if rows else 0.0
    return render_template("partner_earnings.html", rows=rows, total_all=total_all)


# ---------- ADMIN: USER MANAGEMENT ----------

@app.route("/admin/users")
@login_required
@roles_required("coordinator")
def admin_users():
    users = db.session.query(User).order_by(User.id.asc()).all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/users/new", methods=["GET","POST"])
@login_required
@roles_required("coordinator")
def admin_user_create():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = request.form.get("role") or "recruiter"
        is_active_val = request.form.get("is_active", "1")
        is_active = is_active_val == "1"
        partner_tier = (request.form.get("partner_tier") or "Bronze").strip()

        if not email or not password:
            flash("Email и пароль обязательны.", "danger")
            return redirect(url_for("admin_user_create"))

        existing = db.session.query(User).filter(User.email == email).first()
        if existing:
            flash("Пользователь с таким email уже существует.", "danger")
            return redirect(url_for("admin_user_create"))

        user = User(
            name=name or email,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=is_active,
            note=partner_tier,
        )
        db.session.add(user)
        db.session.commit()
        flash("Пользователь создан.", "success")
        return redirect(url_for("admin_users"))

    roles = [
        ("coordinator", "Координатор"),
        ("recruiter", "Рекрутер"),
        ("partner", "Партнёр"),
        ("finance", "Бухгалтер"),
    ]
    return render_template("admin/user_form.html", user=None, roles=roles)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET","POST"])
@login_required
@roles_required("coordinator")
def admin_user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = request.form.get("role") or user.role
        is_active_val = request.form.get("is_active", "1")
        is_active = is_active_val == "1"
        partner_tier = (request.form.get("partner_tier") or (user.note or "Bronze")).strip()

        if not email:
            flash("Email обязателен.", "danger")
            return redirect(url_for("admin_user_edit", user_id=user.id))

        existing = (
            db.session.query(User)
            .filter(User.email == email, User.id != user.id)
            .first()
        )
        if existing:
            flash("Пользователь с таким email уже существует.", "danger")
            return redirect(url_for("admin_user_edit", user_id=user.id))

        user.name = name or email
        user.email = email
        user.role = role
        user.is_active = is_active
        user.note = partner_tier

        if password.strip():
            user.password_hash = generate_password_hash(password)

        db.session.commit()
        flash("Пользователь обновлён.", "success")
        return redirect(url_for("admin_users"))

    roles = [
        ("coordinator", "Координатор"),
        ("recruiter", "Рекрутер"),
        ("partner", "Партнёр"),
        ("finance", "Бухгалтер"),
    ]
    return render_template("admin/user_form.html", user=user, roles=roles)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@roles_required("coordinator")
def admin_user_delete(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == g.user.id:
        flash("Нельзя удалить самого себя.", "danger")
        return redirect(url_for("admin_users"))

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
        return redirect(url_for("admin_users"))

    db.session.delete(user)
    db.session.commit()
    flash("Пользователь удалён.", "success")
    return redirect(url_for("admin_users"))


@app.route("/news")
@login_required
def news_list():
    news = db.session.query(News).filter(News.is_published == True).order_by(News.created_at.desc()).all()
    read_ids = []
    if g.user:
        read_rows = db.session.query(NewsRead.news_id).filter(NewsRead.user_id == g.user.id).all()
        read_ids = [rid for (rid,) in read_rows]
    return render_template("news.html", news_list=news, read_ids=read_ids)

@app.route("/news/<int:news_id>/read", methods=["POST"])
@login_required
def news_mark_read(news_id):
    n = db.session.get(News, news_id)
    if not n or not n.is_published:
        abort(404)
    existing = db.session.query(NewsRead).filter_by(news_id=news_id, user_id=g.user.id).first()
    if not existing:
        db.session.add(NewsRead(news_id=news_id, user_id=g.user.id))
        db.session.commit()
    return redirect(url_for("news_list"))

@app.route("/admin/news")
@login_required
@roles_required("coordinator")
def admin_news():
    news_items = db.session.query(News).order_by(News.created_at.desc()).all()
    return render_template("admin/news_list.html", news_list=news_items)

@app.route("/admin/news/new", methods=["GET", "POST"])
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
        return redirect(url_for("admin_news"))
    return render_template("admin/news_form.html", news=None)

@app.route("/admin/news/<int:news_id>/edit", methods=["GET", "POST"])
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
        return redirect(url_for("admin_news"))
    return render_template("admin/news_form.html", news=n)

@app.route("/admin/news/<int:news_id>/delete", methods=["POST"])
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
    return redirect(url_for("admin_news"))


@app.route("/partner/reports")
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
    )

if __name__ == "__main__":
    init_db(engine)
    app.run(host="0.0.0.0", port=PORT, debug=True)