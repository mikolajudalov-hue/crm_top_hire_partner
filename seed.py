from models import get_engine, init_db, db, User, Job, Candidate, Placement
from werkzeug.security import generate_password_hash
from datetime import date, datetime
import random
from calendar import monthrange

engine = get_engine()
init_db()
db.configure(bind=engine)

random.seed(1337)

def ensure_user(name,email,pwd,role,note="",blocked=False):
    u = db.session.query(User).filter_by(email=email).first()
    if not u:
        u = User(name=name, email=email, password_hash=generate_password_hash(pwd), role=role, is_active=True,
                 note=note, is_blocked=blocked)
        db.session.add(u); db.session.commit()
    return u

admin = ensure_user("Админ", "admin@example.com", "admin123", "coordinator", note="Главный аккаунт")
owner_admin = ensure_user(
    "Mykola Udalov",
    "mykola@udalov.eu",
    "mustang154",
    "coordinator",
    note="Админский аккаунт владельца системы",
)

print("Seed complete: TopHire dataset created.")
