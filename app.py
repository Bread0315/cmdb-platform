"""
CMDB Platform - 主程序入口
"""
import os
import time
import json
from datetime import datetime, timedelta

from flask import Flask, request, session, g, redirect, url_for, flash, jsonify, render_template
from flask_wtf.csrf import CSRFProtect

from config import SESSION_TIMEOUT_HOURS, PASSWORD_EXPIRY_DAYS, logger, access_logger, is_initialized, get_db_config, INIT_CONFIG_FILE
from db import get_db, close_db, init_db

# --------------- 创建应用 ---------------
app = Flask(__name__)
app.secret_key = os.environ.get("CMDB_SECRET", os.urandom(32).hex())

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_TIMEOUT_HOURS),
    WTF_CSRF_ENABLED=True,
    WTF_CSRF_TIME_LIMIT=3600,
)

# --------------- CSRF 保护 ---------------
csrf = CSRFProtect(app)

# --------------- 注册路由 ---------------
from routes import register_routes
register_routes(app)

# --------------- 初始化路由 ---------------
@app.route("/init")
def init_page():
    """初始化页面"""
    if is_initialized():
        return redirect(url_for('auth.login'))
    return render_template("init.html")


@app.route("/init/setup", methods=["POST"])
@csrf.exempt
def init_setup():
    """执行初始化"""
    if is_initialized():
        return jsonify({"success": False, "message": "系统已初始化"})

    try:
        data = request.get_json()
        db_type = data.get("db_type", "sqlite")

        if db_type == "mysql":
            from init_db_mysql import init_mysql_db
            host = data.get("mysql_host", "127.0.0.1")
            port = int(data.get("mysql_port", 3306))
            user = data.get("mysql_user", "root")
            password = data.get("mysql_password", "")
            database = data.get("mysql_database", "cmdb")

            # 测试连接
            import pymysql
            conn = pymysql.connect(host=host, port=port, user=user, password=password, charset='utf8mb4')
            conn.close()

            # 初始化 MySQL
            init_mysql_db(host, port, user, password, database)

            # 保存配置
            config = {
                "db_type": "mysql",
                "mysql_host": host,
                "mysql_port": port,
                "mysql_user": user,
                "mysql_password": password,
                "mysql_database": database,
            }
        else:
            # SQLite 初始化
            from db import _init_sqlite_default_data
            _init_sqlite_default_data()
            config = {"db_type": "sqlite"}

        # 保存配置文件
        with open(INIT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        logger.info(f"系统初始化完成，数据库类型: {db_type}")
        return jsonify({"success": True, "message": "初始化成功"})

    except Exception as e:
        logger.error(f"初始化失败: {e}")
        return jsonify({"success": False, "message": str(e)})


# --------------- 初始化检查中间件 ---------------
@app.before_request
def check_initialized():
    """检查系统是否已初始化"""
    # 允许访问初始化页面和静态资源
    if request.path.startswith('/init') or request.path.startswith('/static'):
        return
    if not is_initialized():
        return redirect(url_for('init_page'))


# --------------- 上下文处理器 ---------------
@app.context_processor
def inject_user():
    if 'user_id' in session:
        try:
            db = get_db()
            config = get_db_config()
            if config.get("db_type") == "mysql":
                cur = db.cursor()
                cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
                user = cur.fetchone()
            else:
                user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
            return {'current_user': user}
        except Exception:
            return {'current_user': None}
    return {'current_user': None}


# --------------- 请求中间件 ---------------
@app.before_request
def log_request_start():
    g.request_start_time = time.time()
    if 'user_id' in session and request.endpoint not in (
        'static', 'auth.logout', 'auth.change_password', 'auth.captcha', 'auth.login'
    ):
        try:
            db = get_db()
            config = get_db_config()
            if config.get("db_type") == "mysql":
                cur = db.cursor()
                cur.execute("SELECT must_change_password, role, password_changed_at FROM users WHERE id=%s", (session['user_id'],))
                user = cur.fetchone()
            else:
                user = db.execute("SELECT must_change_password, role, password_changed_at FROM users WHERE id=?",
                                  (session['user_id'],)).fetchone()
            if user:
                if user['must_change_password'] and request.endpoint != 'auth.change_password':
                    return redirect(url_for('auth.change_password', force=1))
                if user['role'] != 'admin' and user['password_changed_at']:
                    try:
                        last_change = datetime.strptime(user['password_changed_at'], '%Y-%m-%d %H:%M:%S')
                        days_since = (datetime.now() - last_change).days
                        if days_since >= PASSWORD_EXPIRY_DAYS and request.endpoint != 'auth.change_password':
                            flash(f"密码已过期（{days_since}天未更新），请修改密码", "warning")
                            return redirect(url_for('auth.change_password', force=1))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass


@app.after_request
def log_request_end(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
    if request.path.startswith('/static') or request.path.startswith('/init'):
        return response
    duration = time.time() - getattr(g, 'request_start_time', time.time())
    user = session.get('username', '-')
    status = response.status_code
    access_logger.info(f'{request.remote_addr or "-"} {user} {request.method} {request.path} {status} {duration:.3f}s')
    if status >= 400:
        logger.warning(f'{request.remote_addr or "-"} {user} {request.method} {request.path} => {status}')
    return response


@app.teardown_request
def log_request_exception(exc):
    if exc:
        logger.error(f'{request.method} {request.path} 异常: {exc}', exc_info=True)


@app.teardown_appcontext
def close_db_on_teardown(exc):
    close_db(exc)


# --------------- 错误处理 ---------------
@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"服务器错误: {e}", exc_info=True)
    return render_template("errors/500.html"), 500


# --------------- 启动 ---------------
if __name__ == "__main__":
    logger.info("CMDB 平台启动")
    app.run(host="0.0.0.0", port=5000, debug=True)
