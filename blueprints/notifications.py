from flask import Blueprint, render_template, jsonify, g, redirect, url_for, request, flash, abort
from models import db, Notification
from auth_utils import login_required


notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.get("/")
@login_required
def notifications_page():
    user = g.user
    notes = (
        db.session.query(Notification)
        .filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template("notifications.html", notifications=notes)


@notifications_bp.get("/all")
@login_required
def notifications_json():
    user = g.user
    notes = (
        db.session.query(Notification)
        .filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return jsonify(
        [
            {
                "id": n.id,
                "message": n.message,
                "created_at": n.created_at.isoformat(),
                "is_read": n.is_read,
            }
            for n in notes
        ]
    )


@notifications_bp.post("/<int:note_id>/read")
@login_required
def mark_one_read(note_id: int):
    """Отметить одно уведомление как прочитанное."""
    user = g.user
    note = db.session.get(Notification, note_id)
    if not note or note.user_id != user.id:
        abort(404)
    if not note.is_read:
        note.is_read = True
        db.session.commit()
    return redirect(url_for("notifications.notifications_page"))


@notifications_bp.post("/mark-all-read")
@login_required
def mark_all_read():
    """Отметить все уведомления пользователя как прочитанные."""
    user = g.user
    (
        db.session.query(Notification)
        .filter_by(user_id=user.id, is_read=False)
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.session.commit()
    flash("Все уведомления отмечены как прочитанные.", "success")
    return redirect(url_for("notifications.notifications_page"))
