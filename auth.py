"""
CMDB Platform - 认证模块
登录、登出、密码管理、权限装饰器
"""
import re
import io
import time
import random
import string
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, send_file, g
)
from werkzeug.security import generate_password_hash, check_password_hash

from config import (
    MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES,
    PASSWORD_MIN_LENGTH_ADMIN, PASSWORD_MIN_LENGTH_USER,
    PASSWORD_EXPIRY_DAYS, logger
)
from db import get_db, log_to_db

auth_bp = Blueprint('auth', __name__)


# --------------- 密码策略 ---------------
def validate_password(password, role='user'):
    """校验密码强度"""
    min_length = PASSWORD_MIN_LENGTH_ADMIN if role == 'admin' else PASSWORD_MIN_LENGTH_USER
    if len(password) < min_length:
        return False, f"密码长度不少于{min_length}位"
    if len(password) > 128:
        return False, "密码长度不能超过128位"
    checks = [
        (r'[A-Z]', '大写字母'),
        (r'[a-z]', '小写字母'),
        (r'[0-9]', '数字'),
        (r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`]', '特殊字符'),
    ]
    passed = sum(1 for p, _ in checks if re.search(p, password))
    if passed < 3:
        return False, "密码须含大写、小写、数字、特殊字符中的至少3种"
    for i in range(len(password) - 2):
        if password[i] == password[i+1] == password[i+2]:
            return False, "密码不能包含3个以上连续相同字符"
    weak = {'password','12345678','qwertyui','admin123','abc12345','1q2w3e4r','88888888','00000000'}
    if password.lower() in weak:
        return False, "密码过于简单，请更换"
    return True, ""


def is_account_locked(username):
    db = get_db()
    cutoff = (datetime.now() - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')
    cnt = db.execute(
        "SELECT COUNT(*) FROM login_logs WHERE username=? AND success=0 AND created_at>=?",
        (username, cutoff)
    ).fetchone()[0]
    return cnt >= MAX_LOGIN_ATTEMPTS


def get_lockout_remaining(username):
    db = get_db()
    cutoff = (datetime.now() - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')
    row = db.execute(
        "SELECT created_at FROM login_logs WHERE username=? AND success=0 AND created_at>=? ORDER BY created_at DESC LIMIT 1",
        (username, cutoff)
    ).fetchone()
    if row:
        last = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        remain = (last + timedelta(minutes=LOGIN_LOCKOUT_MINUTES) - datetime.now()).total_seconds()
        return max(0, int(remain))
    return 0


# --------------- 权限装饰器 ---------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("请先登录", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            flash("权限不足", "danger")
            return redirect(url_for("dashboard.dashboard"))
        return f(*args, **kwargs)
    return decorated


def write_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if session.get("role") == "viewer":
            flash("只读用户无权操作", "danger")
            return redirect(request.referrer or url_for("dashboard.dashboard"))
        return f(*args, **kwargs)
    return decorated


# --------------- 验证码 ---------------
def generate_captcha():
    """生成图形验证码"""
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choices(chars, k=5))
    try:
        from PIL import Image, ImageDraw, ImageFont
        width, height = 160, 60
        img = Image.new("RGB", (width, height), (240, 240, 240))
        draw = ImageDraw.Draw(img)
        for _ in range(5):
            x1, y1 = random.randint(0, width), random.randint(0, height)
            x2, y2 = random.randint(0, width), random.randint(0, height)
            draw.line((x1, y1, x2, y2), fill=(random.randint(100, 200), random.randint(100, 200), random.randint(100, 200)), width=2)
        for _ in range(50):
            draw.point((random.randint(0, width), random.randint(0, height)), fill=(random.randint(50, 200), random.randint(50, 200), random.randint(50, 200)))
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except (IOError, OSError):
            font = ImageFont.load_default()
        for i, ch in enumerate(code):
            x = 20 + i * 28 + random.randint(-3, 3)
            y = random.randint(5, 15)
            draw.text((x, y), ch, fill=(random.randint(0, 80), random.randint(0, 80), random.randint(0, 80)), font=font)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return code, buf.getvalue()
    except ImportError:
        # Pillow 不可用时返回简单文本验证码
        import hashlib
        return code, hashlib.md5(code.encode()).hexdigest().encode()


# --------------- 认证路由 ---------------
@auth_bp.route("/captcha")
def captcha():
    code, img = generate_captcha()
    session["captcha"] = code.upper()
    session["captcha_time"] = time.time()
    return send_file(io.BytesIO(img), mimetype="image/png")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        captcha_input = request.form.get("captcha", "").strip().upper()
        db = get_db()
        ip = request.remote_addr or ""

        # 验证码校验
        captcha_code = session.pop("captcha", "")
        captcha_time = session.pop("captcha_time", 0)
        if not captcha_input or captcha_input != captcha_code or time.time() - captcha_time > 300:
            flash("验证码错误或已过期", "danger")
            db.execute("INSERT INTO login_logs(username, ip, success) VALUES(?,?,0)", (username, ip))
            db.commit()
            return render_template("login.html")

        if is_account_locked(username):
            remaining = get_lockout_remaining(username)
            minutes = max(1, remaining // 60)
            flash(f"账号已锁定，请{minutes}分钟后重试", "danger")
            logger.warning(f'账号锁定: {username} ({ip})')
            return render_template("login.html")

        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and user["is_active"] and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session.permanent = True
            db.execute("INSERT INTO login_logs(username, ip, success) VALUES(?,?,1)", (username, ip))
            log_to_db(db, 'INFO', '认证', '用户登录', f'{username} 登录成功', username, ip)
            db.commit()
            logger.info(f'用户登录成功: {username} ({ip})')
            # 首次登录强制修改密码
            if user["must_change_password"]:
                flash("首次登录请先修改默认密码", "warning")
                return redirect(url_for("auth.change_password", force=1))
            flash(f"欢迎回来，{user['real_name'] or username}！", "success")
            return redirect(url_for("dashboard.dashboard"))
        else:
            db.execute("INSERT INTO login_logs(username, ip, success) VALUES(?,?,0)", (username, ip))
            log_to_db(db, 'WARNING', '认证', '登录失败', f'{username} 登录失败', username, ip)
            db.commit()
            remaining_attempts = MAX_LOGIN_ATTEMPTS - db.execute(
                "SELECT COUNT(*) FROM login_logs WHERE username=? AND success=0 AND created_at>=?",
                (username, (datetime.now() - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)).strftime('%Y-%m-%d %H:%M:%S'))
            ).fetchone()[0]
            if remaining_attempts > 0:
                flash(f"用户名或密码错误，还可尝试{remaining_attempts}次", "danger")
            else:
                flash(f"登录失败次数过多，账号已锁定{LOGIN_LOCKOUT_MINUTES}分钟", "danger")
            logger.warning(f'登录失败: {username} ({ip}) 剩余{remaining_attempts}次')
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    username = session.get("username", "")
    ip = request.remote_addr or '-'
    db = get_db()
    log_to_db(db, 'INFO', '认证', '用户退出', f'{username} 退出登录', username, ip)
    db.commit()
    logger.info(f'用户退出: {username}')
    session.clear()
    flash("已安全退出", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    force = request.args.get("force", "0") == "1" or request.form.get("force", "0") == "1"
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not old_password or not new_password or not confirm_password:
            flash("所有字段为必填项", "danger")
        elif new_password != confirm_password:
            flash("两次输入的新密码不一致", "danger")
        elif old_password == new_password:
            flash("新密码不能与旧密码相同", "danger")
        else:
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
            if user:
                valid, msg = validate_password(new_password, user['role'])
                if not valid:
                    flash(msg, "danger")
                elif check_password_hash(user['password'], old_password):
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    db.execute(
                        "UPDATE users SET password=?, must_change_password=0, password_changed_at=?, updated_at=datetime('now','localtime') WHERE id=?",
                        (generate_password_hash(new_password), now, session['user_id'])
                    )
                    log_to_db(db, 'INFO', '认证', '修改密码', f"用户 {session.get('username')} 修改密码")
                    db.commit()
                    logger.info(f"用户修改密码: {session.get('username')}")
                    flash("密码修改成功，请重新登录", "success")
                    session.clear()
                    return redirect(url_for("auth.login"))
                else:
                    flash("旧密码错误", "danger")
    return render_template("change_password.html", force=force)
