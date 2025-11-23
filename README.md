# TopHire Business CRM

Приземлённая версия с акцентом на партнёров:
- Названия партнёров на русском (с живыми пометками типа «даёт только грузинов»).
- Заметки по партнёрам (User.note), в том числе «Виктория — не брать кандидатов».
- Блокировка подачи кандидатов от помеченных партнёров (User.is_blocked).
- Брендинг везде: **TopHire Business CRM**.
- Воронка: submitted → to_coordinator → started → no_show.
- Фильтры кандидатов и «Входящие» для рекрутёров/координатора.
- Светлый Apple‑подобный UI с хорошим контрастом.

## Запуск
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python seed.py
python app.py                   # http://localhost:8107/login
```
Демо: admin/admin123, recruiter1/recruit123, partner1/partner123
