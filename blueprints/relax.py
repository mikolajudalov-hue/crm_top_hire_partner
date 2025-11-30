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
)
from constants import PIPELINE
from auth_utils import login_required, roles_required

import os


relax_bp = Blueprint('relax', __name__)

@relax_bp.route("/relax")
@login_required
def relax_home():
    return render_template("relax/relax_home.html")


@relax_bp.route("/relax/stress", methods=["GET", "POST"])
@login_required
def relax_stress():
    """
    Несколько вариантов тестов на стресс.
    Тест выбирается по параметру ?test=... или скрытому полю test_id.
    """
    # Описание доступных тестов
    tests = {
        "daily": {
            "id": "daily",
            "title": "Тест 1. Текущий уровень стресса",
            "subtitle": "Короткий скрининг за последние 3–7 дней: сон, напряжение, концентрация.",
        },
        "burnout": {
            "id": "burnout",
            "title": "Тест 2. Признаки эмоционального выгорания",
            "subtitle": "Помогает понять, не накапливается ли хроническая усталость и циничность.",
        },
        "focus": {
            "id": "focus",
            "title": "Тест 3. Концентрация и отвлечения",
            "subtitle": "Показывает, насколько легко вы удерживаете внимание и не «проваливаетесь» в прокрастинацию.",
        },
        "balance": {
            "id": "balance",
            "title": "Тест 4. Баланс работа/жизнь",
            "subtitle": "Помогает заметить, не вытеснила ли работа всё остальное: отдых, хобби и близких.",
        },
        "energy": {
            "id": "energy",
            "title": "Тест 5. Ресурсность и восстановление",
            "subtitle": "Оценивает, насколько вы успеваете восстанавливаться и пополнять «внутренние батарейки».",
        },
        "anxiety": {
            "id": "anxiety",
            "title": "Тест 6. Уровень тревожности",
            "subtitle": "Помогает понять, насколько часто вас сопровождает чувство тревоги и напряжённые мысли.",
        },
    }

    # Определяем, какой тест сейчас выбран
    test_id = request.args.get("test") or request.form.get("test_id")
    if test_id and test_id not in tests:
        test_id = None

    result = None

    if request.method == "POST" and test_id:
        scores = []
        for name in ["q1", "q2", "q3", "q4", "q5"]:
            raw = request.form.get(name)
            try:
                v = int(raw)
            except (TypeError, ValueError):
                v = 0
            if v < 1 or v > 5:
                v = 0
            scores.append(v)

        answered = [s for s in scores if s > 0]
        if len(answered) < 3:
            flash("Пожалуйста, ответьте хотя бы на большинство вопросов.", "danger")
        else:
            total = sum(answered)

            if test_id == "daily":
                if total <= 10:
                    level = "низкий"
                    msg = "Похоже, сейчас ваш уровень стресса в норме. Продолжайте поддерживать здоровый режим сна, движения и отдыха."
                elif total <= 17:
                    level = "средний"
                    msg = "Есть признаки накопившегося напряжения. Полезны регулярные небольшие паузы, дыхательные практики и микро‑отдых в течение дня."
                else:
                    level = "высокий"
                    msg = "Уровень стресса высокий. Стоит внимательнее отнестись к себе: пересмотреть нагрузку, добавить отдых и при необходимости обсудить ситуацию с руководителем или специалистом."
                history_type = "stress_test_daily"

            elif test_id == "burnout":
                if total <= 10:
                    level = "низкий"
                    msg = "Сильных признаков выгорания сейчас не видно. Продолжайте следить за балансом работы и личного времени."
                elif total <= 17:
                    level = "средний"
                    msg = "Есть отдельные признаки выгорания. Обратите внимание на восстановление и задачи, которые приносят ощущение смысла."
                else:
                    level = "высокий"
                    msg = "Вероятны выраженные признаки выгорания: постоянная усталость, циничность, ощущение бессмысленности. Это сигнал замедлиться и позаботиться о себе."
                history_type = "stress_test_burnout"

            elif test_id == "focus":
                if total <= 10:
                    level = "низкий"
                    msg = "Концентрация в порядке: удаётся удерживать внимание и не слишком часто отвлекаться."
                elif total <= 17:
                    level = "средний"
                    msg = "Иногда отвлечения и прокрастинация мешают, но ситуация поддаётся контролю. Помогут дробление задач и короткие фокус‑сессии."
                else:
                    level = "высокий"
                    msg = "Сосредоточиться очень сложно: постоянно тянет в соцсети, мессенджеры и другие задачи. Стоит пересмотреть нагрузку и попробовать жёсткие фокус‑интервалы."
                history_type = "stress_test_focus"

            elif test_id == "balance":
                if total <= 10:
                    level = "низкий"
                    msg = "Баланс между работой и личной жизнью в целом сохранён."
                elif total <= 17:
                    level = "средний"
                    msg = "Работа иногда забирает слишком много пространства. Подумайте, что можно делегировать или упростить."
                else:
                    level = "высокий"
                    msg = "Работа явно вытесняет отдых и личное время. Это риск выгорания — важно вернуть себе хотя бы небольшие островки времени для себя."
                history_type = "stress_test_balance"

            elif test_id == "energy":
                if total <= 10:
                    level = "низкий"
                    msg = "Ресурса в целом хватает, вы умеете восстанавливаться."
                elif total <= 17:
                    level = "средний"
                    msg = "Запас энергии не всегда стабильный. Поможет более регулярный сон, движение и небольшие радости в течение дня."
                else:
                    level = "высокий"
                    msg = "Чувство опустошённости может говорить о серьёзном дефиците ресурсов. Важно пересмотреть рутину и нагрузку."
                history_type = "stress_test_energy"

            elif test_id == "anxiety":
                if total <= 10:
                    level = "низкий"
                    msg = "Фон тревоги невысокий или эпизодический."
                elif total <= 17:
                    level = "средний"
                    msg = "Тревога периодически даёт о себе знать. Полезны дыхательные практики, ограничение новостного шума и небольшие ритуалы спокойствия."
                else:
                    level = "высокий"
                    msg = "Тревога часто присутствует и мешает жить спокойно. Это важно заметить и при необходимости обсудить со специалистом."
                history_type = "stress_test_anxiety"

            else:
                level = "не определён"
                msg = ""
                history_type = "stress_test"

            rec = RelaxHistory(user_id=g.user.id, type=history_type, value=str(total))
            db.session.add(rec)
            db.session.commit()
            result = {"score": total, "level": level, "message": msg, "test": tests.get(test_id)}

    return render_template(
        "relax/relax_stress.html",
        tests=tests,
        current_test=tests.get(test_id) if test_id else None,
        result=result,
    )


@relax_bp.route("/relax/breath")
@login_required
def relax_breath():
    rec = RelaxHistory(user_id=g.user.id, type="breath", value="1")
    db.session.add(rec)
    db.session.commit()
    return render_template("relax/relax_breath.html")


@relax_bp.route("/relax/exercises")
@login_required
def relax_exercises():
    rec = RelaxHistory(user_id=g.user.id, type="exercise", value="1")
    db.session.add(rec)
    db.session.commit()
    return render_template("relax/relax_exercises.html")


@relax_bp.route("/relax/history")
@login_required
def relax_history():
    history = (
        db.session.query(RelaxHistory)
        .filter(RelaxHistory.user_id == g.user.id)
        .order_by(RelaxHistory.id.desc())
        .all()
    )
    return render_template("relax/relax_history.html", history=history)
