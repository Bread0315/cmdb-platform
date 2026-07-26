"""
CMDB Platform - 部门管理
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required, write_required
from db import get_db, log_to_db
from config import logger

departments_bp = Blueprint('departments', __name__)


@departments_bp.route("/departments")
@login_required
def department_list():
    db = get_db()
    departments = db.execute("""
        SELECT d.*,
            (SELECT COUNT(*) FROM devices WHERE department_id=d.id) as device_count,
            (SELECT COUNT(*) FROM devices WHERE department_id=d.id AND lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name='运行中')) as active_device_count,
            (SELECT COUNT(*) FROM devices WHERE department_id=d.id AND lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name IN ('已下架','已报废'))) as idle_device_count,
            (SELECT COALESCE(SUM(purchase_price), 0) FROM devices WHERE department_id=d.id) as total_value,
            (SELECT COALESCE(SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name='运行中') THEN purchase_price ELSE 0 END), 0) FROM devices WHERE department_id=d.id) as active_value,
            (SELECT COALESCE(SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name IN ('已下架','已报废')) THEN purchase_price ELSE 0 END), 0) FROM devices WHERE department_id=d.id) as idle_value,
            (SELECT name FROM departments WHERE id=d.parent_id) as parent_name
        FROM departments d
        WHERE d.is_active=1
        ORDER BY d.name
    """).fetchall()

    # 为每个部门获取设备类型分布
    dept_device_types = {}
    for dept in departments:
        type_stats = db.execute("""
            SELECT t.name, COUNT(*) as cnt
            FROM devices dev
            JOIN device_types t ON dev.device_type_id=t.id
            WHERE dev.department_id=?
            GROUP BY t.name
            ORDER BY cnt DESC
            LIMIT 3
        """, (dept['id'],)).fetchall()
        dept_device_types[dept['id']] = [{'name': t['name'], 'count': t['cnt']} for t in type_stats]

    return render_template("departments.html", departments=departments, dept_device_types=dept_device_types)


@departments_bp.route("/departments/add", methods=["GET", "POST"])
@write_required
def department_add():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        parent_id = request.form.get("parent_id", type=int) or None
        manager = request.form.get("manager", "").strip()
        cost_center = request.form.get("cost_center", "").strip()
        budget = request.form.get("budget", 0, type=float)
        remark = request.form.get("remark", "").strip()

        if not name:
            flash("部门名称为必填项", "danger")
        else:
            exists = db.execute("SELECT id FROM departments WHERE name=?", (name,)).fetchone()
            if exists:
                flash(f"部门名称 '{name}' 已存在", "danger")
            else:
                db.execute("""INSERT INTO departments(name, code, parent_id, manager, cost_center, budget, remark)
                           VALUES(?,?,?,?,?,?,?)""",
                           (name, code, parent_id, manager, cost_center, budget, remark))
                log_to_db(db, 'INFO', '部门管理', '新增部门', f"新增部门: {name}")
                db.commit()
                flash("部门添加成功", "success")
                return redirect(url_for("departments.department_list"))
    # 获取上级部门列表
    parent_departments = db.execute("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name").fetchall()
    return render_template("department_form.html", department=None, parent_departments=parent_departments, action="add")


@departments_bp.route("/departments/<int:did>/edit", methods=["GET", "POST"])
@write_required
def department_edit(did):
    db = get_db()
    department = db.execute("SELECT * FROM departments WHERE id=?", (did,)).fetchone()
    if not department:
        flash("部门不存在", "danger")
        return redirect(url_for("departments.department_list"))
    back_url = request.args.get("back", url_for("departments.department_list"))
    if request.method == "POST":
        back_url = request.form.get("back", url_for("departments.department_list"))
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        parent_id = request.form.get("parent_id", type=int) or None
        manager = request.form.get("manager", "").strip()
        cost_center = request.form.get("cost_center", "").strip()
        budget = request.form.get("budget", 0, type=float)
        remark = request.form.get("remark", "").strip()

        if not name:
            flash("部门名称为必填项", "danger")
        else:
            # 检查名称唯一性（排除当前部门）
            exists = db.execute("SELECT id FROM departments WHERE name=? AND id!=?", (name, did)).fetchone()
            if exists:
                flash(f"部门名称 '{name}' 已存在", "danger")
            else:
                db.execute("""UPDATE departments SET name=?, code=?, parent_id=?, manager=?, cost_center=?,
                           budget=?, remark=?, updated_at=datetime('now','localtime') WHERE id=?""",
                           (name, code, parent_id, manager, cost_center, budget, remark, did))
                log_to_db(db, 'INFO', '部门管理', '编辑部门', f"更新部门: {name}")
                db.commit()
                flash("部门信息已更新", "success")
                return redirect(back_url)
    # 获取上级部门列表（排除当前部门及其子部门）
    parent_departments = db.execute("SELECT id, name FROM departments WHERE is_active=1 AND id!=? ORDER BY name", (did,)).fetchall()
    return render_template("department_form.html", department=department, parent_departments=parent_departments, action="edit", back_url=back_url)


@departments_bp.route("/departments/<int:did>/delete", methods=["POST"])
@write_required
def department_delete(did):
    db = get_db()
    department = db.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
    if not department:
        flash("部门不存在", "danger")
        return redirect(url_for("departments.department_list"))
    # 检查是否有设备关联
    device_count = db.execute("SELECT COUNT(*) FROM devices WHERE department_id=?", (did,)).fetchone()[0]
    if device_count > 0:
        flash(f"该部门下有 {device_count} 台设备，请先移除设备关联", "danger")
        return redirect(url_for("departments.department_list"))
    # 检查是否有子部门
    child_count = db.execute("SELECT COUNT(*) FROM departments WHERE parent_id=?", (did,)).fetchone()[0]
    if child_count > 0:
        flash(f"该部门下有 {child_count} 个子部门，请先删除子部门", "danger")
        return redirect(url_for("departments.department_list"))
    # 软删除
    db.execute("UPDATE departments SET is_active=0, updated_at=datetime('now','localtime') WHERE id=?", (did,))
    log_to_db(db, 'WARNING', '部门管理', '删除部门', f"删除部门: {department['name']}")
    db.commit()
    flash("部门已删除", "success")
    return redirect(url_for("departments.department_list"))


@departments_bp.route("/api/departments")
@login_required
def api_departments():
    """API: 获取部门列表（用于下拉选择）"""
    db = get_db()
    departments = db.execute("SELECT id, name, code FROM departments WHERE is_active=1 ORDER BY name").fetchall()
    return jsonify([{"id": d["id"], "name": d["name"], "code": d["code"]} for d in departments])


@departments_bp.route("/departments/devices")
@departments_bp.route("/departments/<int:did>/devices")
@login_required
def department_devices(did=None):
    """部门设备列表"""
    db = get_db()

    # 获取所有部门（用于筛选）
    departments = db.execute("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name").fetchall()

    # 当前筛选的部门
    dept_name = None
    if did:
        dept = db.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
        if dept:
            dept_name = dept['name']

    # 查询参数
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    keyword = request.args.get("q", "").strip()
    type_id = request.args.get("type", "").strip()
    state_id = request.args.get("state", "").strip()
    cat_filter = request.args.get("cat", "").strip()

    # 构建查询条件
    where = []
    params = []
    if did:
        where.append("d.department_id=?")
        params.append(did)
    if keyword:
        where.append("(d.name LIKE ? OR d.serial_number LIKE ? OR d.biz_ip LIKE ? OR d.brand LIKE ?)")
        like = f"%{keyword}%"
        params += [like, like, like, like]
    if type_id:
        where.append("d.device_type_id=?")
        params.append(type_id)
    if state_id:
        where.append("d.lifecycle_state_id=?")
        params.append(state_id)
    if cat_filter:
        where.append("t.category=?")
        params.append(cat_filter)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    base_from = """
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        LEFT JOIN cabinets c ON d.cabinet_id=c.id
        LEFT JOIN rooms r1 ON c.room_id=r1.id
        LEFT JOIN rooms r2 ON d.room_id=r2.id
        LEFT JOIN departments dept ON d.department_id=dept.id
    """
    total = db.execute(f"SELECT COUNT(*) {base_from} {where_sql}", params).fetchone()[0]
    devices = db.execute(f"""
        SELECT d.*, d.u_height, t.name as type_name, t.category, s.name as state_name, s.sort as state_sort,
               c.name as cabinet_name, COALESCE(r1.name, r2.name) as room_name, dept.name as dept_name
        {base_from}
        {where_sql}
        ORDER BY d.updated_at DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, (page - 1) * per_page]).fetchall()

    # 获取设备类型列表
    types = db.execute("SELECT * FROM device_types ORDER BY category, name").fetchall()
    states = db.execute("SELECT * FROM lifecycle_states WHERE name IN ('运行中', '已下架', '已报废') ORDER BY sort").fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template("department_devices.html", devices=devices, departments=departments,
                           dept_id=did, dept_name=dept_name, types=types, states=states,
                           page=page, total_pages=total_pages, total=total,
                           keyword=keyword, type_id=type_id, state_id=state_id, cat_filter=cat_filter)
