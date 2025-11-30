from functools import wraps
from flask import g, redirect, url_for, session
from models import db, User


def load_user():
    """Загружает текущего пользователя в g.user."""
    user_id = session.get("user_id")
    if user_id:
        g.user = db.session.get(User, user_id)
    else:
        g.user = None


def login_required(f):
    """Доступ только для авторизованных пользователей."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def current_user_or_none():
    """
    Возвращает текущего пользователя, если он залогинен.
    Если нет — возвращает None, чтобы не падало.
    """
    try:
        from flask import g
        return getattr(g, "user", None)
    except Exception:
        return None

def roles_required(*roles):
    """
    Доступ только для пользователей с определённой ролью:
    @roles_required("recruiter")
    @roles_required("recruiter", "coordinator")
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            allowed = list(roles)
            if "coordinator" in roles:
                allowed.append("director")
            if g.user.role not in allowed:
                # Если роль не подходит → отправляем на главную
                return redirect(url_for("main.index"))
            return f(*args, **kwargs)
        return wrapper
    return decorator
