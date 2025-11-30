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
    Notification,
    create_notification_for_users,
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
)
from constants import PIPELINE
from auth_utils import login_required, roles_required

import os


jobs_bp = Blueprint('jobs', __name__)

@jobs_bp.route("/jobs")
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


@jobs_bp.route("/jobs/<int:job_id>/pin", methods=["POST"])
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
    return redirect(url_for("jobs.jobs"))


@jobs_bp.route("/jobs/new", methods=["GET","POST"])
@login_required
@roles_required("coordinator", "recruiter")
def job_new():
    if request.method == "POST":
        gender_pref = (request.form.get("gender_preference") or "").strip()
        age_to_raw = (request.form.get("age_to") or "").strip()
        try:
            age_to_val = int(age_to_raw) if age_to_raw else 0
        except ValueError:
            age_to_val = 0

        # Сколько людей нужно по вакансии
        needed_male_raw = (request.form.get("needed_male") or "").strip()
        needed_female_raw = (request.form.get("needed_female") or "").strip()
        try:
            needed_male = int(needed_male_raw) if needed_male_raw else 0
        except ValueError:
            needed_male = 0
        try:
            needed_female = int(needed_female_raw) if needed_female_raw else 0
        except ValueError:
            needed_female = 0
        allow_family_couples = bool(request.form.get("allow_family_couples"))

        # Статус
        status = (request.form.get("status") or "active").strip()
        if status not in ("active", "inactive"):
            status = "active"

        # Надбавка для кандидатов-мужчин
        male_bonus_enabled = bool(request.form.get("male_bonus_enabled"))
        try:
            male_bonus_percent = float(request.form.get("male_bonus_percent") or 0)
        except ValueError:
            male_bonus_percent = 0.0

        j = Job(
            title=(request.form.get("title") or "").strip(),
            location=(request.form.get("location") or "").strip(),
            description=(request.form.get("description") or "").strip(),
            short_description=(request.form.get("short_description") or "").strip(),
            priority=request.form.get("priority","normal"),
            gender_preference=gender_pref,
            age_to=age_to_val,
            needed_male=needed_male,
            needed_female=needed_female,
            allow_family_couples=allow_family_couples,
            partner_fee_amount=float(request.form.get("partner_fee_amount") or 0),
            recruiter_fee_amount=float(request.form.get("recruiter_fee_amount") or 0),
            promo_multiplier=float(request.form.get("promo_multiplier") or 1.0),
            promo_label=(request.form.get("promo_label") or "").strip(),
            status=status,
            male_bonus_enabled=male_bonus_enabled,
            male_bonus_percent=male_bonus_percent
        )
        db.session.add(j)
        db.session.flush()

        # Обложка вакансии (картинка в списке)
        file = request.files.get("thumbnail_image")
        if file and file.filename:
            upload_root = os.path.join(os.path.dirname(__file__), "uploads", "job_thumbs")
            os.makedirs(upload_root, exist_ok=True)
            job_dir = os.path.join(upload_root, str(j.id))
            os.makedirs(job_dir, exist_ok=True)
            safe_name = secure_filename(file.filename)
            if safe_name:
                # проверяем коллизии
                base, ext = os.path.splitext(safe_name)
                rel_name = os.path.join(str(j.id), safe_name)
                save_path = os.path.join(upload_root, rel_name)
                counter = 1
                while os.path.exists(save_path) and counter < 1000:
                    cand = f"{base}_{counter}{ext}"
                    rel_name = os.path.join(str(j.id), cand)
                    save_path = os.path.join(upload_root, rel_name)
                    counter += 1
                file.save(save_path)
                j.thumbnail_image = rel_name

        # Фотографии проживания
        files = request.files.getlist("housing_photos")
        if files:
            upload_root = os.path.join(os.path.dirname(__file__), "uploads", "job_housing")
            os.makedirs(upload_root, exist_ok=True)
            job_dir = os.path.join(upload_root, str(j.id))
            os.makedirs(job_dir, exist_ok=True)
            for f in files:
                if not f or not f.filename:
                    continue
                safe_name = secure_filename(f.filename)
                if not safe_name:
                    continue
                base, ext = os.path.splitext(safe_name)
                rel_name = os.path.join(str(j.id), safe_name)
                save_path = os.path.join(upload_root, rel_name)
                counter = 1
                while os.path.exists(save_path) and counter < 1000:
                    cand = f"{base}_{counter}{ext}"
                    rel_name = os.path.join(str(j.id), cand)
                    save_path = os.path.join(upload_root, rel_name)
                    counter += 1
                f.save(save_path)
                ph = JobHousingPhoto(job_id=j.id, filename=rel_name, label="")
                db.session.add(ph)

        db.session.commit()

        # Уведомления о новой вакансии всем рекрутёрам и партнёрам
        recipients = [
            u.id
            for u in db.session.query(User).filter(User.role.in_(["recruiter", "partner"]), User.is_active == True).all()
        ]
        if recipients:
            create_notification_for_users(
                recipients,
                f"Новая вакансия: {j.title} ({j.location})"
            )

        flash("Вакансия создана", "success")
        return redirect(url_for("jobs.jobs"))
    return render_template("job_new.html")


@jobs_bp.route("/job-thumb/<int:job_id>")
@login_required
def job_thumb(job_id):
    j = db.session.get(Job, job_id)
    if not j or j.status == "deleted":
        abort(404)
    if not j.thumbnail_image:
        abort(404)

    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "job_thumbs")
    rel_name = j.thumbnail_image
    candidates = []
    candidates.append(os.path.join(upload_root, rel_name))

    # fallback: если в базе только имя файла без подкаталога
    if rel_name and os.sep not in rel_name and "/" not in rel_name:
        candidates.append(os.path.join(upload_root, str(job_id), rel_name))

    final_path = None
    for path in candidates:
        if path and os.path.exists(path):
            final_path = path
            break

    if not final_path:
        abort(404)

    directory, filename = os.path.split(final_path)
    return send_from_directory(directory, filename)


@jobs_bp.route("/jobs/<int:job_id>/housing-photo/<int:photo_id>")
@login_required
def job_housing_photo(job_id, photo_id):
    ph = db.session.get(JobHousingPhoto, photo_id)
    if not ph or ph.job_id != job_id:
        abort(404)

    upload_root = os.path.join(os.path.dirname(__file__), "uploads", "job_housing")
    rel_name = ph.filename

    candidates = []
    if rel_name:
        candidates.append(os.path.join(upload_root, rel_name))
        # на случай, если файл лежит прямо в папке job_id
        if os.sep not in rel_name and "/" not in rel_name:
            candidates.append(os.path.join(upload_root, str(job_id), rel_name))

    final_path = None
    for path in candidates:
        if path and os.path.exists(path):
            final_path = path
            break

    if not final_path:
        abort(404)

    directory, filename = os.path.split(final_path)
    return send_from_directory(directory, filename)


@jobs_bp.route("/jobs/<int:job_id>")
@login_required
def job_view(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)
    photos = db.session.query(JobHousingPhoto).filter(JobHousingPhoto.job_id == job_id).order_by(JobHousingPhoto.id).all()
    return render_template("job_view.html", job=j, housing_photos=photos)


@jobs_bp.route("/jobs/<int:job_id>/promo", methods=["POST"])
@login_required
@roles_required("coordinator", "recruiter")
def job_promo_update(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)
    j.promo_multiplier = float(request.form.get("promo_multiplier") or 1.0)
    j.promo_label = (request.form.get("promo_label") or "").strip()
    db.session.commit()
    flash("Акция по вакансии обновлена", "success")
    return redirect(url_for("jobs.job_view", job_id=job_id))


@jobs_bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
@roles_required("coordinator", "recruiter")
def job_delete(job_id):
    j = db.session.get(Job, job_id)
    if not j:
        abort(404)

    # Мягкое удаление: помечаем вакансию как удалённую, кандидатов не трогаем
    j.status = "deleted"
    j.priority = "low"

    # Уведомление рекрутёрам и партнёрам об удалении вакансии
    recipients = [
        u.id
        for u in db.session.query(User).filter(User.role.in_(["recruiter", "partner"]), User.is_active == True).all()
    ]
    if recipients:
        create_notification_for_users(
            recipients,
            f"Вакансия удалена: {j.title} ({j.location})"
        )

    db.session.commit()
    flash("Вакансия помечена как удалённая. Кандидаты сохранены.", "success")
    return redirect(url_for("jobs.jobs"))


@jobs_bp.route("/jobs/<int:job_id>/edit", methods=["GET","POST"])
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

        # Сколько людей нужно по вакансии
        needed_male_raw = (request.form.get("needed_male") or "").strip()
        needed_female_raw = (request.form.get("needed_female") or "").strip()
        try:
            j.needed_male = int(needed_male_raw) if needed_male_raw else 0
        except ValueError:
            j.needed_male = 0
        try:
            j.needed_female = int(needed_female_raw) if needed_female_raw else 0
        except ValueError:
            j.needed_female = 0
        j.allow_family_couples = bool(request.form.get("allow_family_couples"))
        age_to_raw = (request.form.get("age_to") or "").strip()
        try:
            j.age_to = int(age_to_raw) if age_to_raw else 0
        except ValueError:
            j.age_to = 0

        j.partner_fee_amount = float(request.form.get("partner_fee_amount") or 0)
        j.recruiter_fee_amount = float(request.form.get("recruiter_fee_amount") or 0)
        j.promo_multiplier = float(request.form.get("promo_multiplier") or 1.0)
        j.promo_label = (request.form.get("promo_label") or "").strip()

        # Надбавка для кандидатов-мужчин
        j.male_bonus_enabled = bool(request.form.get("male_bonus_enabled"))
        try:
            j.male_bonus_percent = float(request.form.get("male_bonus_percent") or 0)
        except ValueError:
            j.male_bonus_percent = 0.0

        # Обложка вакансии (картинка в списке)
        file = request.files.get("thumbnail_image")
        if file and file.filename:
            upload_root = os.path.join(os.path.dirname(__file__), "uploads", "job_thumbs")
            os.makedirs(upload_root, exist_ok=True)
            job_dir = os.path.join(upload_root, str(j.id))
            os.makedirs(job_dir, exist_ok=True)
            safe_name = secure_filename(file.filename)
            if safe_name:
                rel_name = os.path.join(str(j.id), safe_name)
                save_path = os.path.join(upload_root, rel_name)
                # если файл уже существует, слегка изменяем имя
                if os.path.exists(save_path):
                    base, ext = os.path.splitext(safe_name)
                    counter = 1
                    while True:
                        candidate_name = f"{base}_{counter}{ext}"
                        rel_name = os.path.join(str(j.id), candidate_name)
                        save_path = os.path.join(upload_root, rel_name)
                        if not os.path.exists(save_path):
                            break
                        counter += 1
                file.save(save_path)
                j.thumbnail_image = rel_name
        # Фотографии проживания
        files = request.files.getlist("housing_photos")
        if files:
            upload_root = os.path.join(os.path.dirname(__file__), "uploads", "job_housing")
            os.makedirs(upload_root, exist_ok=True)
            job_dir = os.path.join(upload_root, str(j.id))
            os.makedirs(job_dir, exist_ok=True)
            for f in files:
                if not f or not f.filename:
                    continue
                safe_name = secure_filename(f.filename)
                if not safe_name:
                    continue
                base, ext = os.path.splitext(safe_name)
                rel_name = os.path.join(str(j.id), safe_name)
                save_path = os.path.join(upload_root, rel_name)
                counter = 1
                while os.path.exists(save_path) and counter < 1000:
                    cand = f"{base}_{counter}{ext}"
                    rel_name = os.path.join(str(j.id), cand)
                    save_path = os.path.join(upload_root, rel_name)
                    counter += 1
                f.save(save_path)
                ph = JobHousingPhoto(job_id=j.id, filename=rel_name, label="")
                db.session.add(ph)

        status = (request.form.get("status") or "active").strip()
        if status not in ("active", "inactive"):
            status = "active"
        j.status = status

        db.session.commit()

        # Уведомления об изменении вакансии всем рекрутёрам и партнёрам
        recipients = [
            u.id
            for u in db.session.query(User).filter(User.role.in_(["recruiter", "partner"]), User.is_active == True).all()
        ]
        if recipients:
            create_notification_for_users(
                recipients,
                f"Вакансия обновлена: {j.title} ({j.location})"
            )

        flash("Вакансия обновлена", "success")
        return redirect(url_for("jobs.job_view", job_id=j.id))

    photos = db.session.query(JobHousingPhoto).filter(JobHousingPhoto.job_id == job_id).order_by(JobHousingPhoto.id).all()
    return render_template("job_edit.html", job=j, housing_photos=photos)


@jobs_bp.route("/jobs/<int:job_id>/submit", methods=["GET","POST"])
@login_required
def job_submit(job_id):
    j = db.session.get(Job, job_id)
    if not j or j.status!="active": abort(404)
    # Блокировка подачи от запрещённых партнёров
    if g.user.role == "partner" and g.user.is_blocked:
        flash("Ваш аккаунт помечен как ограниченный: подача кандидатов недоступна. Обратитесь к администратору.", "danger")
        return redirect(url_for("main.index"))
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

        # Фиксируем комиссию на момент подачи (с учётом текущего бустера и мужского бонуса)
        base_partner_offer = (j.partner_fee_amount or 0.0) * (j.promo_multiplier or 1.0)

        # Пол кандидата
        candidate_gender = (request.form.get("candidate_gender") or "").strip()
        if candidate_gender not in ("male", "female"):
            candidate_gender = ""

        # Если включён мужской бонус и кандидат — мужчина, увеличиваем комиссию
        if candidate_gender == "male" and getattr(j, "male_bonus_enabled", False) and (getattr(j, "male_bonus_percent", 0) or 0) > 0:
            base_partner_offer = base_partner_offer * (1 + (getattr(j, "male_bonus_percent", 0) or 0) / 100.0)

        partner_offer = base_partner_offer
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
            gender = candidate_gender,
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

        doc_type = (request.form.get("doc_type") or "").strip()
        if doc_type:
            doc_type_map = {
                "visa": "Виза",
                "residence_card": "Карта побыта",
                "visa_free": "Безвиз",
                "other": "Другое",
            }
            doc_label = doc_type_map.get(doc_type, doc_type)
            prefix = f"Тип документа: {doc_label}"
            if c.notes:
                c.notes = prefix + " | " + c.notes
            else:
                c.notes = prefix

        db.session.commit()
        flash(f"Кандидат «{c.full_name}» отправлен на вакансию «{j.title}».", "success")
        if g.user.role in ("recruiter","coordinator","director"):
            return redirect(url_for("main.inbox"))
        return redirect(url_for("main.index"))
    return render_template("candidate_submit.html", job=j)
