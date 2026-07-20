"""
CMDB Platform - 系统日志
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import admin_required
from db import get_db, log_to_db
from config import logger

logs_bp = Blueprint('logs', __name__)


@logs_bp.route("/logs")
@admin_required
def log_viewer():
    db = get_db()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50
    level_filter = request.args.get("level", "").strip()
    module_filter = request.args.get("module", "").strip()
    keyword = request.args.get("q", "").strip()

    where, params = [], []
    if level_filter:
        where.append("level=?")
        params.append(level_filter)
    if module_filter:
        where.append("module=?")
        params.append(module_filter)
    if keyword:
        where.append("(detail LIKE ? OR username LIKE ? OR action LIKE ?)")
        like = f"%{keyword}%"
        params += [like, like, like]

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.execute(f"SELECT COUNT(*) FROM system_logs {where_sql}", params).fetchone()[0]
    logs = db.execute(f"""
        SELECT * FROM system_logs {where_sql}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
    """, params + [per_page, (page - 1) * per_page]).fetchall()

    modules = db.execute("SELECT DISTINCT module FROM system_logs WHERE module != '' ORDER BY module").fetchall()

    stats = {
        'total': db.execute("SELECT COUNT(*) FROM system_logs").fetchone()[0],
        'info': db.execute("SELECT COUNT(*) FROM system_logs WHERE level='INFO'").fetchone()[0],
        'warning': db.execute("SELECT COUNT(*) FROM system_logs WHERE level='WARNING'").fetchone()[0],
        'error': db.execute("SELECT COUNT(*) FROM system_logs WHERE level='ERROR'").fetchone()[0],
        'today': db.execute("SELECT COUNT(*) FROM system_logs WHERE date(created_at)=date('now','localtime')").fetchone()[0],
    }

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template("logs.html", logs=logs, stats=stats, modules=modules,
                           page=page, total_pages=total_pages, total=total,
                           level_filter=level_filter, module_filter=module_filter, keyword=keyword)


@logs_bp.route("/logs/clear", methods=["POST"])
@admin_required
def log_clear():
    days = request.form.get("days", 30, type=int)
    db = get_db()
    db.execute("DELETE FROM system_logs WHERE created_at < datetime('now', '-' || ? || ' days', 'localtime')", (days,))
    db.commit()
    logger.info(f"清理 {days} 天前的系统日志 by {session.get('username')}")
    flash(f"已清理 {days} 天前的日志", "success")
    return redirect(url_for("logs.log_viewer"))
