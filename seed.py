from models import get_engine, init_db, db, User, Job, Candidate, Placement
from werkzeug.security import generate_password_hash
from datetime import date, datetime
import random
from calendar import monthrange

engine = get_engine()
init_db(engine)
db.configure(bind=engine)

random.seed(1337)

def ensure_user(name,email,pwd,role,note="",blocked=False):
    u = db.session.query(User).filter_by(email=email).first()
    if not u:
        u = User(name=name, email=email, password_hash=generate_password_hash(pwd), role=role, is_active=True,
                 note=note, is_blocked=blocked)
        db.session.add(u); db.session.commit()
    return u

admin = ensure_user("Координатор", "admin@example.com", "admin123", "coordinator", note="Главный аккаунт")
recruiters = [
    ensure_user("Мария (HR)", "recruiter1@example.com", "recruit123", "recruiter", note="Аккуратно проверяет документы"),
    ensure_user("Андрей (HR)", "recruiter2@example.com", "recruit234", "recruiter", note="Любит быстрые созвоны"),
    ensure_user("Оля (HR)", "recruiter3@example.com", "recruit345", "recruiter", note="Держит связь с партнёрами"),
]
partners = [
    ensure_user("Тбилиси HR", "partner1@example.com", "partner123", "partner", note="даёт только грузинов"),
    ensure_user("Виктория", "partner2@example.com", "partner234", "partner", note="не брать кандидатов", blocked=True),
    ensure_user("Душанбинский центр", "partner3@example.com", "partner345", "partner", note="часто спрашивает про жильё"),
    ensure_user("Рома — частник", "partner4@example.com", "partner456", "partner", note="любит всё по-честному"),
]

def ensure_job(**kw):
    j = db.session.query(Job).filter_by(title=kw["title"]).first()
    if not j:
        j = Job(**kw); db.session.add(j); db.session.commit()
    return j

cities = ["Вроцлав","Познань","Лодзь","Варшава","Гданьск","Катовице","Краков","Щецин","Люблин","Быдгощ"]
titles = ["Грузчик","Комплектовщик","Оператор линии","Сортировщик","Курьер","Работник производства","Сварщик","Слесарь","Электрик","Водитель B",
          "Контролёр качества","Помощник склада","Пикер","Монтажник"]
descriptions = ["Смены 2/3", "Лёгкая работа", "Есть ночные", "Оформление официально", "Премии за посещаемость",
                "Возможны надчасы", "Стабильный график", "Физическая работа"]
priorities = ["urgent","normal","low"]

jobs = []
for i in range(18):
    title = f"{random.choice(titles)} ({random.choice(cities)})"
    jobs.append(ensure_job(
        title=title,
        location=title.split("(")[-1].rstrip(")"),
        description=random.choice(descriptions),
        priority=random.choices(priorities, weights=[4,5,1])[0],
        partner_fee_amount=random.choice([350,400,450,500,550,600,700,900]),
        recruiter_fee_amount=random.choice([120,150,180,200,220,300]),
        status="active"
    ))

first_names = ["Иван","Анна","Пётр","Мария","Томас","Ольга","Давид","Ева","Михаил","Екатерина","Павел","Агнешка","Кирилл","Моника","Лукаш","Наталия","Рафаэль","Зузанна","Матей","Александра","Якуб","Виктор","Магда","Кинга"]
last_names  = ["Ковалёв","Новак","Зелинский","Вишневская","Левандовский","Качмарек","Пёнтек","Лис","Вуйчик","Каминьска","Домбровский","Мазур","Кравчик","Зайонц","Кроль","Вечорек","Шиманский","Янковска","Яворский","Рутковска"]

def last_day_of_month(y, m):
    return monthrange(y, m)[1]

today = date.today()

def ym_before(n):
    y, m = today.year, today.month
    m -= n
    while m <= 0:
        y -= 1; m += 12
    return y, m

for months_ago in range(0, 12):
    y, m = ym_before(months_ago)
    days = last_day_of_month(y, m)

    n_sub = random.randint(30, 60)
    for i in range(n_sub):
        fname = random.choice(first_names)
        lname = random.choice(last_names)
        uniq = f"{y%100}{m:02d}{i:03d}"
        full_name = f"{fname} {lname} {uniq}"
        partner = random.choice(partners)
        job = random.choice(jobs)

        created_day = random.randint(1, min(days, 26))
        created_dt = datetime(y, m, created_day, random.randint(8, 17), random.choice([0,15,30,45]))
        c = Candidate(full_name=full_name, submitter_id=partner.id, job_id=job.id, status="Подан", created_at=created_dt)
        db.session.add(c)
        db.session.flush()

        r = random.random()
        if r < 0.18:
            c.status = "Подан"
        elif r < 0.6 and not partner.is_blocked:
            from datetime import date as _d
            start_day = min(created_day + random.randint(1, 12), days)
            start_date = _d(y, m, start_day).strftime("%Y-%m-%d")
            recruiter = random.choice(recruiters)
            p = Placement(candidate_id=c.id, job_id=job.id, recruiter_id=recruiter.id,
                          start_date=start_date,
                          partner_commission=job.partner_fee_amount,
                          recruiter_commission=job.recruiter_fee_amount,
                          status="Вышел на работу")
            c.status = "Вышел на работу"
            db.session.add(p)
        elif r < 0.72:
            c.status = "Не вышел"

    db.session.commit()

print("Seed complete: TopHire dataset created.")
