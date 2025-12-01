import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    """Базовая конфигурация Flask-приложения."""

    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

    # База данных
    # Универсальная строка подключения, которую будет использовать Alembic
    # Теперь используется только переменная окружения DATABASE_URL
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

    # Произвольные настройки приложения
    BRAND = os.environ.get("APP_BRAND", "TopHire Business CRM")
    LANG_CHOICES = os.environ.get("LANG_CHOICES", "ru,uk").split(",")
