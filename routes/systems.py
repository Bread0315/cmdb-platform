"""
CMDB Platform - 业务系统管理
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from auth import login_required, write_required
from db import get_db, log_to_db
from config import logger

systems_bp = Blueprint('systems', __name__)


@systems_bp.route("/systems")
@login_required
def system_list():
    db = get_db()
    systems = db.execute("""
        SELECT bs.*,
            (SELECT COUNT(*) FROM system_device_rel sdr
             JOIN devices d ON sdr.device_id=d.id
             JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
             WHERE sdr.system_id=bs.id AND s.name NOT IN ('已下架', '已报废')) as device_count,
            u.username as creator_name
        FROM business_systems bs
        LEFT JOIN users u ON bs.created_by=u.id
        ORDER BY bs.updated_at DESC
    """).fetchall()
    return render_template("systems.html", systems=systems)


@systems_bp.route("/systems/add", methods=["GET", "POST"])
@write_required
def system_add():
    db = get_db()
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "name", "sys_type", "status", "department", "owner", "developer",
            "description", "biz_domain", "tech_stack", "db_info", "middleware",
            "deploy_path", "source_repo", "monitor_url", "remark"
        ]}
        if not data["name"]:
            flash("系统名称为必填项", "danger")
        else:
            cur = db.execute("""
                INSERT INTO business_systems(name, sys_type, status, department, owner, developer,
                    description, biz_domain, tech_stack, db_info, middleware,
                    deploy_path, source_repo, monitor_url, remark, created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (data["name"], data["sys_type"], data["status"] or "running", data["department"], data["owner"],
                  data["developer"], data["description"], data["biz_domain"], data["tech_stack"], data["db_info"],
                  data["middleware"], data["deploy_path"], data["source_repo"], data["monitor_url"],
                  data["remark"], session["user_id"]))
            system_id = cur.lastrowid
            device_ids = request.form.getlist("device_ids")
            for did in device_ids:
                role = request.form.get(f"device_role_{did}", "").strip()
                db.execute("INSERT OR IGNORE INTO system_device_rel(system_id, device_id, role) VALUES(?,?,?)",
                           (system_id, int(did), role))
            log_to_db(db, 'INFO', '业务系统', '新增系统', f"新增系统: {data['name']} (关联{len(device_ids)}台设备)")
            db.commit()
            logger.info(f"新增业务系统: {data['name']} by {session.get('username')}")
            flash(f"业务系统 '{data['name']}' 创建成功", "success")
            return redirect(url_for("systems.system_list"))
    devices = db.execute("""
        SELECT d.id, d.name, t.name as type_name, t.category, d.biz_ip
        FROM devices d JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE s.name NOT IN ('已下架', '已报废')
        ORDER BY d.name
    """).fetchall()
    return render_template("system_form.html", system=None, devices=devices, action="add")


@systems_bp.route("/systems/<int:sid>/edit", methods=["GET", "POST"])
@write_required
def system_edit(sid):
    db = get_db()
    system = db.execute("SELECT * FROM business_systems WHERE id=?", (sid,)).fetchone()
    if not system:
        abort(404)
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "name", "sys_type", "status", "department", "owner", "developer",
            "description", "biz_domain", "tech_stack", "db_info", "middleware",
            "deploy_path", "source_repo", "monitor_url", "remark"
        ]}
        if not data["name"]:
            flash("系统名称为必填项", "danger")
        else:
            db.execute("""
                UPDATE business_systems SET name=?, sys_type=?, status=?, department=?, owner=?, developer=?,
                    description=?, biz_domain=?, tech_stack=?, db_info=?, middleware=?,
                    deploy_path=?, source_repo=?, monitor_url=?, remark=?,
                    updated_at=datetime('now','localtime')
                WHERE id=?
            """, (data["name"], data["sys_type"], data["status"], data["department"], data["owner"],
                  data["developer"], data["description"], data["biz_domain"], data["tech_stack"], data["db_info"],
                  data["middleware"], data["deploy_path"], data["source_repo"], data["monitor_url"],
                  data["remark"], sid))
            db.execute("DELETE FROM system_device_rel WHERE system_id=?", (sid,))
            device_ids = request.form.getlist("device_ids")
            for did in device_ids:
                role = request.form.get(f"device_role_{did}", "").strip()
                db.execute("INSERT OR IGNORE INTO system_device_rel(system_id, device_id, role) VALUES(?,?,?)",
                           (sid, int(did), role))
            db.commit()
            flash("业务系统信息已更新", "success")
            return redirect(url_for("systems.system_list"))
    devices = db.execute("""
        SELECT d.id, d.name, t.name as type_name, t.category, d.biz_ip
        FROM devices d JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE s.name NOT IN ('已下架', '已报废')
        ORDER BY d.name
    """).fetchall()
    rels = db.execute("SELECT device_id, role FROM system_device_rel WHERE system_id=?", (sid,)).fetchall()
    linked = {r[0]: r[1] for r in rels}
    return render_template("system_form.html", system=system, devices=devices, linked=linked, action="edit")


@systems_bp.route("/systems/<int:sid>/delete", methods=["POST"])
@write_required
def system_delete(sid):
    db = get_db()
    system = db.execute("SELECT name FROM business_systems WHERE id=?", (sid,)).fetchone()
    if not system:
        abort(404)
    log_to_db(db, 'WARNING', '业务系统', '删除系统', f"删除业务系统: {system['name']}")
    db.execute("DELETE FROM business_systems WHERE id=?", (sid,))
    db.commit()
    logger.warning(f"删除业务系统: {system['name']} by {session.get('username')}")
    flash("业务系统已删除", "success")
    return redirect(url_for("systems.system_list"))


@systems_bp.route("/systems/<int:sid>")
@login_required
def system_detail(sid):
    db = get_db()
    system = db.execute("SELECT * FROM business_systems WHERE id=?", (sid,)).fetchone()
    if not system:
        abort(404)
    devices = db.execute("""
        SELECT d.*, t.name as type_name, t.category, s.name as state_name,
               c.name as cabinet_name, r.name as room_name, sdr.role
        FROM system_device_rel sdr
        JOIN devices d ON sdr.device_id=d.id
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        LEFT JOIN cabinets c ON d.cabinet_id=c.id
        LEFT JOIN rooms r ON c.room_id=r.id
        WHERE sdr.system_id=? AND s.name NOT IN ('已下架', '已报废')
    """, (sid,)).fetchall()
    return render_template("system_detail.html", system=system, devices=devices)
