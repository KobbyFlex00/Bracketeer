from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db, login_manager
from .models import AdminUser

bp = Blueprint("auth", __name__, url_prefix="/admin")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(AdminUser, int(user_id))


def _safe_next(target):
    if target and urlsplit(target).netloc == "" and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("admin.home")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.home"))
    if request.method == "POST":
        user = AdminUser.query.filter_by(username=request.form.get("username", "").strip()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(_safe_next(request.args.get("next")))
        flash("Wrong username or password.", "danger")
    return render_template("admin/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("public.home"))
