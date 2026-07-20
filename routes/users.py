"""
CMDB Platform - 用户管理
"""
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash
from auth import admin_required, validate_password
from db import get_db, log_to_db
from config import logger

users_bp = Blueprint('users', __name__)


@users_bp.route("/users")
@admin_required
def user_list():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return render_template("users.html", users=users)


@users_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def user_add():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        real_name = request.form.get("real_name", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "user")
        if not username or not password:
            flash("用户名和密码为必填项", "danger")
        else:
            valid, msg = validate_password(password, role)
            if not valid:
                flash(msg, "danger")
            else:
                db = get_db()
                try:
                    db.execute(
                        "INSERT INTO users(username, password, real_name, email, role, must_change_password) VALUES(?,?,?,?,?,1)",
                        (username, generate_password_hash(password), real_name, email, role)
                    )
                    log_to_db(db, 'INFO', '用户管理', '新增用户', f"新增用户: {username} (角色:{role})")
                    db.commit()
                    logger.info(f"新增用户: {username} by {session.get('username')}")
                    flash(f"用户 {username} 创建成功", "success")
                    return redirect(url_for("users.user_list"))
                except sqlite3.IntegrityError:
                    flash("用户名已存在", "danger")
    return render_template("user_form.html", user=None, action="add")


@users_bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        abort(404)
    if request.method == "POST":
        real_name = request.form.get("real_name", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "user")
        is_active = 1 if request.form.get("is_active") else 0
        new_password = request.form.get("password", "").strip()

        if new_password:
            valid, msg = validate_password(new_password, role)
            if not valid:
                flash(msg, "danger")
                return render_template("user_form.html", user=user, action="edit")
        try:
            if new_password:
                db.execute("UPDATE users SET real_name=?, email=?, role=?, is_active=?, password=?, updated_at=datetime('now','localtime') WHERE id=?",
                           (real_name, email, role, is_active, generate_password_hash(new_password), uid))
            else:
                db.execute("UPDATE users SET real_name=?, email=?, role=?, is_active=?, updated_at=datetime('now','localtime') WHERE id=?",
                           (real_name, email, role, is_active, uid))
            db.commit()
            flash("用户信息已更新", "success")
            return redirect(url_for("users.user_list"))
        except Exception as e:
            flash(f"更新失败: {e}", "danger")
    return render_template("user_form.html", user=user, action="edit")


@users_bp.route("/users/<int:uid>/delete", methods=["POST"])
@admin_required
def user_delete(uid):
    if uid == session.get("user_id"):
        flash("不能删除当前登录用户", "danger")
        return redirect(url_for("users.user_list"))
    db = get_db()
    log_to_db(db, 'WARNING', '用户管理', '删除用户', f"删除用户 ID:{uid}")
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    logger.warning(f"删除用户 ID:{uid} by {session.get('username')}")
    flash("用户已删除", "success")
    return redirect(url_for("users.user_list"))
