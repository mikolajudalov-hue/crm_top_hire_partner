import time
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth_utils import login_required, current_user_or_none
from models import db, TrainingSection, TrainingLesson, TrainingPartnerQuizQuestion, TrainingPartnerQuizResult, TrainingLessonProgress

training_bp = Blueprint("training", __name__)


@training_bp.route("/training")
@login_required
def index():
    sections = (
        db.session.query(TrainingSection)
        .filter(TrainingSection.is_active == True)
        .order_by(TrainingSection.sort_order, TrainingSection.id)
        .all()
    )
    return render_template("training_index.html", sections=sections)


@training_bp.route("/training/section/<int:section_id>")
@login_required
def section(section_id: int):
    section = db.session.get(TrainingSection, section_id)
    if not section or not section.is_active:
        flash("Раздел обучения не найден или отключён.", "warning")
        return redirect(url_for("training.index"))

    lessons = (
        db.session.query(TrainingLesson)
        .filter(
            TrainingLesson.section_id == section.id,
            TrainingLesson.is_published == True,
        )
        .order_by(TrainingLesson.sort_order, TrainingLesson.id)
        .all()
    )

    # Прогресс по урокам для текущего пользователя
    user = current_user_or_none()
    progress_ids = set()
    if user:
        lesson_ids = [l.id for l in lessons]
        if lesson_ids:
            rows = (
                db.session.query(TrainingLessonProgress.lesson_id)
                .filter(
                    TrainingLessonProgress.user_id == user.id,
                    TrainingLessonProgress.lesson_id.in_(lesson_ids),
                )
                .all()
            )
            progress_ids = {row[0] for row in rows}

    return render_template(
        "training_section.html",
        section=section,
        lessons=lessons,
        progress_ids=progress_ids,
    )


@training_bp.route("/training/lesson/<int:lesson_id>")
@login_required
def lesson(lesson_id: int):
    lesson = db.session.get(TrainingLesson, lesson_id)
    if not lesson or not lesson.is_published:
        flash("Урок не найден или скрыт.", "warning")
        return redirect(url_for("training.index"))

    section = db.session.get(TrainingSection, lesson.section_id)

    siblings = (
        db.session.query(TrainingLesson)
        .filter(
            TrainingLesson.section_id == lesson.section_id,
            TrainingLesson.is_published == True,
        )
        .order_by(TrainingLesson.sort_order, TrainingLesson.id)
        .all()
    )
    prev_lesson = None
    next_lesson = None
    for idx, l in enumerate(siblings):
        if l.id == lesson.id:
            if idx > 0:
                prev_lesson = siblings[idx - 1]
            if idx + 1 < len(siblings):
                next_lesson = siblings[idx + 1]
            break

    # Отмечаем прогресс
    user = current_user_or_none()
    if user:
        existing = (
            db.session.query(TrainingLessonProgress)
            .filter(
                TrainingLessonProgress.user_id == user.id,
                TrainingLessonProgress.lesson_id == lesson.id,
            )
            .first()
        )
        if not existing:
            db.session.add(TrainingLessonProgress(user_id=user.id, lesson_id=lesson.id))
            db.session.commit()

    return render_template(
        "training_lesson.html",
        section=section,
        lesson=lesson,
        prev_lesson=prev_lesson,
        next_lesson=next_lesson,
    )

@training_bp.route("/training/partner-quiz", methods=["GET", "POST"])
@login_required
def partner_quiz():
    questions = (
        db.session.query(TrainingPartnerQuizQuestion)
        .filter(TrainingPartnerQuizQuestion.is_active == True)
        .order_by(TrainingPartnerQuizQuestion.sort_order, TrainingPartnerQuizQuestion.id)
        .all()
    )

    if request.method == "POST":
        if not questions:
            flash("Вопросы теста ещё не настроены.", "warning")
            return redirect(url_for("training.index"))

        total_score = 0
        max_score = 5 * len(questions)
        answers = {}
        for q in questions:
            raw = request.form.get(f"q_{q.id}") or "3"
            try:
                val = int(raw)
            except ValueError:
                val = 3
            val = max(1, min(5, val))
            total_score += val
            answers[str(q.id)] = val

        percent = (total_score / max_score) * 5  # приводим к шкале 1–5

        if percent >= 4.2:
            level = "топ‑партнёр"
            msg = "У вас уже очень сильный уровень сервиса и партнёрского подхода. Дальше — только масштабирование объёмов."
        elif percent >= 3.4:
            level = "хороший партнёр"
            msg = "Вы уже надёжный партнёр, но есть несколько зон роста: посмотрите на вопросы, где вы ставили себе 3 или ниже."
        else:
            level = "есть над чем поработать"
            msg = "Тест показывает, что часть процессов стоит улучшить. Используйте уроки в разделе 'Работа с партнёрами' и 'Сервис и этика'."

        user = current_user_or_none()
        result = TrainingPartnerQuizResult(
            user_id=user.id if user else None,
            score=percent,
            max_score=5,
            level=level,
            answers_json=json.dumps(answers, ensure_ascii=False),
            created_at=datetime.utcnow(),
        )
        db.session.add(result)
        db.session.commit()

        flash("Результаты теста сохранены.", "success")
        return render_template(
            "training_partner_quiz_result.html",
            questions=questions,
            answers=answers,
            level=level,
            score=round(percent, 2),
            message=msg,
        )

    return render_template("training_partner_quiz.html", questions=questions)


def _require_training_admin():
    from flask import g
    user = current_user_or_none()
    if not user or user.role not in ("admin", "director"):
        flash("Недостаточно прав для управления обучением.", "warning")
        return False
    return True


@training_bp.route("/training/admin/lessons")
@login_required
def admin_lessons():
    if not _require_training_admin():
        return redirect(url_for("training.index"))

    sections = (
        db.session.query(TrainingSection)
        .order_by(TrainingSection.sort_order, TrainingSection.id)
        .all()
    )
    sections_map = {s.id: s for s in sections}

    lessons = (
        db.session.query(TrainingLesson)
        .order_by(TrainingLesson.section_id, TrainingLesson.sort_order, TrainingLesson.id)
        .all()
    )

    return render_template(
        "training_admin_lessons.html",
        lessons=lessons,
        sections_map=sections_map,
    )


@training_bp.route("/training/admin/lessons/new", methods=["GET", "POST"])
@login_required
def admin_lesson_new():
    if not _require_training_admin():
        return redirect(url_for("training.index"))

    sections = (
        db.session.query(TrainingSection)
        .order_by(TrainingSection.sort_order, TrainingSection.id)
        .all()
    )
    if not sections:
        flash("Сначала создайте хотя бы один раздел обучения (через базу данных).", "warning")
        return redirect(url_for("training.index"))

    if request.method == "POST":
        section_id = int(request.form.get("section_id") or sections[0].id)
        title = (request.form.get("title") or "").strip()
        slug = (request.form.get("slug") or "").strip()
        image_url = (request.form.get("image_url") or "").strip()
        estimated_minutes_raw = (request.form.get("estimated_minutes") or "").strip()
        sort_order_raw = (request.form.get("sort_order") or "").strip()
        content = (request.form.get("content") or "").strip()
        is_published = bool(request.form.get("is_published"))

        if not title:
            flash("Название урока обязательно.", "danger")
            return render_template(
                "training_admin_lesson_form.html",
                sections=sections,
                lesson=None,
                form=request.form,
            )

        try:
            estimated_minutes = int(estimated_minutes_raw) if estimated_minutes_raw else 10
        except ValueError:
            estimated_minutes = 10

        try:
            sort_order = int(sort_order_raw) if sort_order_raw else 10
        except ValueError:
            sort_order = 10

        if not slug:
            slug = f"lesson-{section_id}-{int(time.time())}"

        lesson = TrainingLesson(
            section_id=section_id,
            slug=slug,
            title=title,
            content=content,
            image_url=image_url,
            estimated_minutes=estimated_minutes,
            sort_order=sort_order,
            is_published=is_published,
        )
        db.session.add(lesson)
        db.session.commit()
        flash("Урок создан.", "success")
        return redirect(url_for("training.admin_lessons"))

    return render_template(
        "training_admin_lesson_form.html",
        sections=sections,
        lesson=None,
        form=None,
    )


@training_bp.route("/training/admin/lessons/<int:lesson_id>/edit", methods=["GET", "POST"])
@login_required
def admin_lesson_edit(lesson_id: int):
    if not _require_training_admin():
        return redirect(url_for("training.index"))

    lesson = db.session.get(TrainingLesson, lesson_id)
    if not lesson:
        flash("Урок не найден.", "warning")
        return redirect(url_for("training.admin_lessons"))

    sections = (
        db.session.query(TrainingSection)
        .order_by(TrainingSection.sort_order, TrainingSection.id)
        .all()
    )

    if request.method == "POST":
        section_id = int(request.form.get("section_id") or lesson.section_id)
        title = (request.form.get("title") or "").strip()
        slug = (request.form.get("slug") or "").strip()
        image_url = (request.form.get("image_url") or "").strip()
        estimated_minutes_raw = (request.form.get("estimated_minutes") or "").strip()
        sort_order_raw = (request.form.get("sort_order") or "").strip()
        content = (request.form.get("content") or "").strip()
        is_published = bool(request.form.get("is_published"))

        if not title:
            flash("Название урока обязательно.", "danger")
            return render_template(
                "training_admin_lesson_form.html",
                sections=sections,
                lesson=lesson,
                form=request.form,
            )

        try:
            estimated_minutes = int(estimated_minutes_raw) if estimated_minutes_raw else lesson.estimated_minutes
        except ValueError:
            estimated_minutes = lesson.estimated_minutes or 10

        try:
            sort_order = int(sort_order_raw) if sort_order_raw else lesson.sort_order
        except ValueError:
            sort_order = lesson.sort_order or 10

        if not slug:
            slug = lesson.slug or f"lesson-{section_id}-{int(time.time())}"

        lesson.section_id = section_id
        lesson.title = title
        lesson.slug = slug
        lesson.image_url = image_url
        lesson.estimated_minutes = estimated_minutes
        lesson.sort_order = sort_order
        lesson.content = content
        lesson.is_published = is_published

        db.session.commit()
        flash("Урок сохранён.", "success")
        return redirect(url_for("training.admin_lessons"))

    # initial form values come from lesson
    return render_template(
        "training_admin_lesson_form.html",
        sections=sections,
        lesson=lesson,
        form=None,
    )
