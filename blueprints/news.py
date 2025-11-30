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


news_bp = Blueprint('news', __name__)

@news_bp.route("/news")
@login_required
def news_list():
    news = db.session.query(News).filter(News.is_published == True).order_by(News.created_at.desc()).all()
    read_ids = []
    if g.user:
        read_rows = db.session.query(NewsRead.news_id).filter(NewsRead.user_id == g.user.id).all()
        read_ids = [rid for (rid,) in read_rows]
    return render_template("news.html", news_list=news, read_ids=read_ids)


@news_bp.route("/news/<int:news_id>/read", methods=["POST"])
@login_required
def news_mark_read(news_id):
    n = db.session.get(News, news_id)
    if not n or not n.is_published:
        abort(404)
    existing = db.session.query(NewsRead).filter_by(news_id=news_id, user_id=g.user.id).first()
    if not existing:
        db.session.add(NewsRead(news_id=news_id, user_id=g.user.id))
        db.session.commit()
    return redirect(url_for("news.news_list"))
