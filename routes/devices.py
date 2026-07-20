"""
CMDB Platform - 设备管理
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from auth import login_required, write_required
from db import get_db, log_to_db
from config import logger

devices_bp = Blueprint('devices', __name__)


@devices_bp.route("/devices")
@login_required
def device_list():
    db = get_db()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    keyword = request.args.get("q", "").strip()
    type_id = request.args.get("type", "").strip()
    state_id = request.args.get("state", "").strip()
    cat_filter = request.args.get("cat", "").strip()
    room_filter = request.args.get("room", "").strip()
    warranty_filter = request.args.get("warranty", "").strip()

    where, params = [], []
    if keyword:
        where.append("(d.name LIKE ? OR d.serial_number LIKE ? OR d.biz_ip LIKE ? OR d.brand LIKE ? OR r1.name LIKE ? OR r2.name LIKE ?)")
        like = f"%{keyword}%"
        params += [like, like, like, like, like, like]
    if type_id:
        where.append("d.device_type_id=?")
        params.append(type_id)
    if state_id:
        if ',' in state_id:
            ids = [x.strip() for x in state_id.split(',') if x.strip()]
            placeholders = ','.join('?' * len(ids))
            where.append(f"d.lifecycle_state_id IN ({placeholders})")
            params.extend(ids)
        else:
            where.append("d.lifecycle_state_id=?")
            params.append(state_id)
    if cat_filter:
        where.append("t.category=?")
        params.append(cat_filter)
    if room_filter:
        where.append("(r1.id=? OR r2.id=?)")
        params.extend([room_filter, room_filter])
    if warranty_filter == 'soon':
        where.append("d.warranty_date != '' AND d.warranty_date <= date('now', '+30 days') AND d.warranty_date >= date('now')")

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    base_from = """
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        LEFT JOIN cabinets c ON d.cabinet_id=c.id
        LEFT JOIN rooms r1 ON c.room_id=r1.id
        LEFT JOIN rooms r2 ON d.room_id=r2.id
    """
    total = db.execute(f"SELECT COUNT(*) {base_from} {where_sql}", params).fetchone()[0]
    devices = db.execute(f"""
        SELECT d.*, d.u_height, t.name as type_name, t.category, s.name as state_name, s.sort as state_sort,
               c.name as cabinet_name, COALESCE(r1.name, r2.name) as room_name
        {base_from}
        {where_sql}
        ORDER BY d.updated_at DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, (page - 1) * per_page]).fetchall()

    if cat_filter:
        types = db.execute("SELECT * FROM device_types WHERE category=? ORDER BY name", (cat_filter,)).fetchall()
    else:
        types = db.execute("SELECT * FROM device_types ORDER BY category, name").fetchall()
    states = db.execute("SELECT * FROM lifecycle_states WHERE name IN ('运行中', '已下架', '已报废') ORDER BY sort").fetchall()
    rooms = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    cabinets = db.execute("SELECT * FROM cabinets ORDER BY name").fetchall()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template("devices.html", devices=devices, types=types, states=states, cabinets=cabinets, rooms=rooms,
                           page=page, total_pages=total_pages, total=total,
                           keyword=keyword, type_id=type_id, state_id=state_id, cat_filter=cat_filter,
                           room_filter=room_filter, warranty_filter=warranty_filter)


@devices_bp.route("/devices/add", methods=["GET", "POST"])
@write_required
def device_add():
    db = get_db()
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "name", "brand", "model", "serial_number", "biz_ip", "oob_ip",
            "mac_address", "u_position", "location", "department", "custodian",
            "rack_date", "warranty_date", "purchase_price", "remark", "tag",
            "asset_code", "user_name"
        ]}
        type_id = request.form.get("device_type_id", type=int)
        state_id = request.form.get("lifecycle_state_id", type=int)
        cabinet_id = request.form.get("cabinet_id", type=int) or None
        room_id = request.form.get("room_id_single", type=int) or None
        u_height = request.form.get("u_height", 1, type=int)
        quantity = request.form.get("quantity", 1, type=int)
        software_ids = request.form.getlist("software_ids")
        hardware_ids = request.form.getlist("hardware_ids")
        if u_height not in (1, 2, 4):
            u_height = 1
        if not data["name"] or not type_id or not state_id:
            flash("设备名称、类型、生命周期状态为必填项", "danger")
        else:
            cur = db.execute("""
                INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                    biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height, location, department, custodian,
                    rack_date, warranty_date, purchase_price, lifecycle_state_id, remark, tag, quantity,
                    asset_code, user_name, room_id, created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (data["name"], type_id, data["brand"], data["model"], data["serial_number"],
                  data["biz_ip"], data["oob_ip"], data["mac_address"], cabinet_id, data["u_position"], u_height,
                  data["location"], data["department"], data["custodian"], data["rack_date"], data["warranty_date"],
                  float(data["purchase_price"] or 0), state_id, data["remark"], data["tag"], quantity,
                  data["asset_code"], data["user_name"], room_id, session["user_id"]))
            device_id = cur.lastrowid
            db.execute("INSERT INTO device_logs(device_id, user_id, action, detail) VALUES(?,?,?,?)",
                       (device_id, session["user_id"], "新增设备", f"新增设备: {data['name']}"))
            log_to_db(db, 'INFO', '资产管理', '新增设备', f"新增设备: {data['name']} (类型ID:{type_id})")

            # 保存关联关系
            for sw_id in software_ids:
                db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                          (device_id, 'device', int(sw_id), 'device', 'runs_on', ''))
            for hw_id in hardware_ids:
                db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                          (int(hw_id), 'device', device_id, 'device', 'runs_on', ''))

            db.commit()
            logger.info(f"新增设备: {data['name']} by {session.get('username')}")
            flash("设备添加成功", "success")
            return redirect(url_for("devices.device_list"))
    types = db.execute("SELECT * FROM device_types ORDER BY name").fetchall()
    states = db.execute("SELECT * FROM lifecycle_states WHERE name IN ('运行中', '已下架', '已报废') ORDER BY sort").fetchall()
    rooms = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    cabinets = db.execute("SELECT * FROM cabinets ORDER BY name").fetchall()
    all_software = db.execute("SELECT d.id, d.name, t.name as type_name FROM devices d JOIN device_types t ON d.device_type_id=t.id WHERE t.category='software' ORDER BY d.name").fetchall()
    all_hardware = db.execute("SELECT d.id, d.name, t.name as type_name FROM devices d JOIN device_types t ON d.device_type_id=t.id WHERE t.category='hardware' ORDER BY d.name").fetchall()
    return render_template("device_form.html", device=None, types=types, states=states, rooms=rooms, cabinets=cabinets,
                          all_software=all_software, all_hardware=all_hardware, action="add")


@devices_bp.route("/devices/<int:did>/edit", methods=["GET", "POST"])
@write_required
def device_edit(did):
    db = get_db()
    device = db.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
    if not device:
        abort(404)
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "name", "brand", "model", "serial_number", "biz_ip", "oob_ip",
            "mac_address", "u_position", "location", "department", "custodian",
            "rack_date", "warranty_date", "purchase_price", "remark", "tag",
            "asset_code", "user_name"
        ]}
        type_id = request.form.get("device_type_id", type=int)
        state_id = request.form.get("lifecycle_state_id", type=int)
        cabinet_id = request.form.get("cabinet_id", type=int) or None
        room_id = request.form.get("room_id_single", type=int) or None
        u_height = request.form.get("u_height", 1, type=int)
        quantity = request.form.get("quantity", 1, type=int)
        software_ids = request.form.getlist("software_ids")
        hardware_ids = request.form.getlist("hardware_ids")
        if u_height not in (1, 2, 4):
            u_height = 1
        old_state = device["lifecycle_state_id"]
        if not data["name"] or not type_id or not state_id:
            flash("设备名称、类型、生命周期状态为必填项", "danger")
        else:
            db.execute("""
                UPDATE devices SET name=?, device_type_id=?, brand=?, model=?, serial_number=?,
                    biz_ip=?, oob_ip=?, mac_address=?, cabinet_id=?, u_position=?, u_height=?,
                    location=?, department=?, custodian=?,
                    rack_date=?, warranty_date=?, purchase_price=?, lifecycle_state_id=?,
                    remark=?, tag=?, quantity=?, asset_code=?, user_name=?, room_id=?,
                    updated_at=datetime('now','localtime')
                WHERE id=?
            """, (data["name"], type_id, data["brand"], data["model"], data["serial_number"],
                  data["biz_ip"], data["oob_ip"], data["mac_address"], cabinet_id, data["u_position"], u_height,
                  data["location"], data["department"], data["custodian"], data["rack_date"], data["warranty_date"],
                  float(data["purchase_price"] or 0), state_id, data["remark"], data["tag"], quantity,
                  data["asset_code"], data["user_name"], room_id, did))
            if old_state != state_id:
                old_s = db.execute("SELECT name FROM lifecycle_states WHERE id=?", (old_state,)).fetchone()
                new_s = db.execute("SELECT name FROM lifecycle_states WHERE id=?", (state_id,)).fetchone()
                db.execute("INSERT INTO device_logs(device_id, user_id, action, detail) VALUES(?,?,?,?)",
                           (did, session["user_id"], "状态变更", f"{old_s['name']} → {new_s['name']}"))
            db.execute("INSERT INTO device_logs(device_id, user_id, action, detail) VALUES(?,?,?,?)",
                       (did, session["user_id"], "编辑设备", f"更新设备信息: {data['name']}"))
            log_to_db(db, 'INFO', '资产管理', '编辑设备', f"更新设备: {data['name']} (ID:{did})")

            # 更新关联关系：先删除旧的，再插入新的
            db.execute("DELETE FROM ci_relationships WHERE (source_id=? AND source_type='device') OR (target_id=? AND target_type='device')", (did, did))
            for sw_id in software_ids:
                db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                          (did, 'device', int(sw_id), 'device', 'runs_on', ''))
            for hw_id in hardware_ids:
                db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                          (int(hw_id), 'device', did, 'device', 'runs_on', ''))

            db.commit()
            logger.info(f"编辑设备: {data['name']} (ID:{did}) by {session.get('username')}")
            flash("设备更新成功", "success")
            return redirect(url_for("devices.device_list"))
    types = db.execute("SELECT * FROM device_types ORDER BY name").fetchall()
    states = db.execute("SELECT * FROM lifecycle_states WHERE name IN ('运行中', '已下架', '已报废') ORDER BY sort").fetchall()
    rooms = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    cabinets = db.execute("SELECT * FROM cabinets ORDER BY name").fetchall()
    all_software = db.execute("SELECT d.id, d.name, t.name as type_name FROM devices d JOIN device_types t ON d.device_type_id=t.id WHERE t.category='software' ORDER BY d.name").fetchall()
    all_hardware = db.execute("SELECT d.id, d.name, t.name as type_name FROM devices d JOIN device_types t ON d.device_type_id=t.id WHERE t.category='hardware' ORDER BY d.name").fetchall()
    
    # 当前设备已关联的软件和硬件
    device_software = db.execute("""
        SELECT d.id, d.name, t.name as type_name
        FROM ci_relationships cr
        JOIN devices d ON cr.target_id=d.id
        JOIN device_types t ON d.device_type_id=t.id
        WHERE cr.source_id=? AND cr.source_type='device' AND cr.target_type='device'
    """, (did,)).fetchall()
    device_hardware = db.execute("""
        SELECT d.id, d.name, t.name as type_name
        FROM ci_relationships cr
        JOIN devices d ON cr.source_id=d.id
        JOIN device_types t ON d.device_type_id=t.id
        WHERE cr.target_id=? AND cr.source_type='device' AND cr.target_type='device'
    """, (did,)).fetchall()
    
    return render_template("device_form.html", device=device, types=types, states=states, rooms=rooms, cabinets=cabinets,
                          all_software=all_software, all_hardware=all_hardware,
                          device_software=device_software, device_hardware=device_hardware, action="edit")


@devices_bp.route("/devices/<int:did>/delete", methods=["POST"])
@write_required
def device_delete(did):
    db = get_db()
    device = db.execute("SELECT name FROM devices WHERE id=?", (did,)).fetchone()
    if not device:
        abort(404)
    db.execute("DELETE FROM devices WHERE id=?", (did,))
    log_to_db(db, 'WARNING', '资产管理', '删除设备', f"删除设备: {device['name']} (ID:{did})")
    db.commit()
    logger.warning(f"删除设备: {device['name']} (ID:{did}) by {session.get('username')}")
    flash("设备已删除", "success")
    return redirect(url_for("devices.device_list"))


@devices_bp.route("/devices/<int:did>")
@login_required
def device_detail(did):
    db = get_db()
    device = db.execute("""
        SELECT d.*, t.name as type_name, t.category, s.name as state_name, c.name as cabinet_name,
               COALESCE(r1.name, r2.name) as room_name
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        LEFT JOIN cabinets c ON d.cabinet_id=c.id
        LEFT JOIN rooms r1 ON c.room_id=r1.id
        LEFT JOIN rooms r2 ON d.room_id=r2.id
        WHERE d.id=?
    """, (did,)).fetchone()
    if not device:
        abort(404)
    logs = db.execute("""
        SELECT l.*, u.username FROM device_logs l
        LEFT JOIN users u ON l.user_id=u.id
        WHERE l.device_id=? ORDER BY l.created_at DESC
    """, (did,)).fetchall()
    systems = db.execute("""
        SELECT bs.*, sdr.role
        FROM system_device_rel sdr
        JOIN business_systems bs ON sdr.system_id=bs.id
        WHERE sdr.device_id=?
    """, (did,)).fetchall()

    # 关联的软件资产（此设备运行的软件：source=device -> target=software）
    software_assets = db.execute("""
        SELECT d.id, d.name, d.brand, d.model, t.name as type_name, t.category, cr.rel_type, cr.remark
        FROM ci_relationships cr
        JOIN devices d ON cr.target_id=d.id
        JOIN device_types t ON d.device_type_id=t.id
        WHERE cr.source_id=? AND cr.source_type='device' AND cr.target_type='device'
    """, (did,)).fetchall()

    # 关联的硬件资产（运行此软件的硬件：source=hardware -> target=device）
    hardware_assets = db.execute("""
        SELECT d.id, d.name, d.brand, d.model, t.name as type_name, t.category, cr.rel_type, cr.remark
        FROM ci_relationships cr
        JOIN devices d ON cr.source_id=d.id
        JOIN device_types t ON d.device_type_id=t.id
        WHERE cr.target_id=? AND cr.source_type='device' AND cr.target_type='device'
    """, (did,)).fetchall()

    sw_list = [dict(r) for r in software_assets]
    hw_list = [dict(r) for r in hardware_assets]

    return render_template("device_detail.html", device=device, logs=logs, systems=systems,
                          software_assets=sw_list, hardware_assets=hw_list)


@devices_bp.route("/device-types", methods=["GET", "POST"])
@login_required
def device_types():
    db = get_db()
    if request.method == "POST" and session.get("role") == "admin":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "other").strip()
        if name:
            try:
                db.execute("INSERT INTO device_types(name, category) VALUES(?,?)", (name, category))
                db.commit()
                flash(f"设备类型 '{name}' 已添加", "success")
            except Exception:
                flash("类型名称已存在", "danger")
        return redirect(url_for("devices.device_types"))
    types = db.execute("""
        SELECT t.*, (SELECT COUNT(*) FROM devices WHERE device_type_id=t.id) as device_count
        FROM device_types t ORDER BY t.category, t.name
    """).fetchall()
    return render_template("device_types.html", types=types)


@devices_bp.route("/device-types/<int:tid>/delete", methods=["POST"])
@login_required
def device_type_delete(tid):
    if session.get("role") != "admin":
        abort(403)
    db = get_db()
    cnt = db.execute("SELECT COUNT(*) FROM devices WHERE device_type_id=?", (tid,)).fetchone()[0]
    if cnt > 0:
        flash(f"该类型下有 {cnt} 台设备，无法删除", "danger")
    else:
        db.execute("DELETE FROM device_types WHERE id=?", (tid,))
        db.commit()
        flash("设备类型已删除", "success")
    return redirect(url_for("devices.device_types"))


@devices_bp.route("/devices/batch-edit", methods=["POST"])
@write_required
def device_batch_edit():
    db = get_db()
    ids_str = request.form.get("ids", "").strip()
    if not ids_str:
        flash("请选择设备", "danger")
        return redirect(url_for("devices.device_list"))

    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        flash("无效的设备ID", "danger")
        return redirect(url_for("devices.device_list"))

    lifecycle_state_id = request.form.get("lifecycle_state_id", "").strip()
    room_id = request.form.get("room_id", "").strip()
    custodian = request.form.get("custodian", "").strip()
    department = request.form.get("department", "").strip()
    tag = request.form.get("tag", "").strip()

    placeholders = ','.join('?' * len(ids))
    updates = []
    params = []

    if lifecycle_state_id:
        updates.append("lifecycle_state_id=?")
        params.append(int(lifecycle_state_id))
    if room_id:
        updates.append("room_id=?")
        params.append(int(room_id))
    if custodian:
        updates.append("custodian=?")
        params.append(custodian)
    if department:
        updates.append("department=?")
        params.append(department)
    if tag:
        # 追加标签
        for did in ids:
            existing = db.execute("SELECT tag FROM devices WHERE id=?", (did,)).fetchone()
            if existing:
                old_tag = existing['tag'] or ''
                new_tags = [t.strip() for t in tag.split(',') if t.strip()]
                old_tags = [t.strip() for t in old_tag.split(',') if t.strip()]
                merged = list(dict.fromkeys(old_tags + new_tags))
                db.execute("UPDATE devices SET tag=? WHERE id=?", (','.join(merged), did))

    if updates:
        sql = f"UPDATE devices SET {', '.join(updates)} WHERE id IN ({placeholders})"
        db.execute(sql, params + ids)

    db.commit()
    flash(f"成功修改 {len(ids)} 台设备", "success")
    return redirect(url_for("devices.device_list"))


@devices_bp.route("/devices/batch-delete", methods=["POST"])
@write_required
def device_batch_delete():
    db = get_db()
    ids_str = request.form.get("ids", "").strip()
    if not ids_str:
        flash("请选择设备", "danger")
        return redirect(url_for("devices.device_list"))

    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        flash("无效的设备ID", "danger")
        return redirect(url_for("devices.device_list"))

    placeholders = ','.join('?' * len(ids))
    db.execute(f"DELETE FROM devices WHERE id IN ({placeholders})", ids)
    db.commit()
    flash(f"成功删除 {len(ids)} 台设备", "success")
    return redirect(url_for("devices.device_list"))
