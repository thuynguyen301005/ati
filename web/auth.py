from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from services import db


auth_bp = Blueprint("auth", __name__)


def current_user_id() -> int | None:
    return session.get("user_id")



def login_required(view):
    """Trang thì chuyển về /login, API thì trả 401."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user_id():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please sign in again."}), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper



def _safe_next(target: str | None) -> str:
    # Chỉ cho redirect nội bộ, tránh open redirect.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("auth.home")



@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user_id():
        return redirect(url_for("auth.home"))
    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.get_user_by_email(email)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(_safe_next(request.args.get("next")))
        error = "Incorrect email or password."
    return render_template("auth.html", mode="login", error=error, email=email)



@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user_id():
        return redirect(url_for("auth.home"))
    error = None
    email = ""
    name = ""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not name or len(name) > 80:
            error = "Enter your name (up to 80 characters)."
        elif "@" not in email or len(email) > 254:
            error = "Enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            user_id = db.create_user(email, generate_password_hash(password), name)
            if user_id is None:
                error = "An account with this email already exists."
            else:
                session.clear()
                session["user_id"] = user_id
                session.permanent = True
                return redirect(url_for("auth.home"))
    return render_template("auth.html", mode="register", error=error, email=email, name=name)



@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))



def _spec_page(project_id: str = ""):
    user = db.get_user(current_user_id())
    if not user:
        session.clear()
        return redirect(url_for("auth.login"))
    if project_id and not db.get_project(user["id"], project_id):
        return redirect(url_for("auth.home"))
    user["display_name"] = user.get("name") or user["email"].split("@")[0]
    return render_template("spec.html", user=user, project_id=project_id)



@auth_bp.route("/")
@login_required
def home():
    return _spec_page()



@auth_bp.route("/spec/<project_id>")
@login_required
def open_specification(project_id):
    return _spec_page(project_id)
