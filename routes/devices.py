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
    dept_filter = request.args.get("dept", "").strip()
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
    if dept_filter:
        where.append("d.department_id=?")
        params.append(dept_filter)
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

    if cat_filter:
        types = db.execute("SELECT * FROM device_types WHERE category=? ORDER BY name", (cat_filter,)).fetchall()
    else:
        types = db.execute("SELECT * FROM device_types ORDER BY category, name").fetchall()
    states = db.execute("SELECT * FROM lifecycle_states WHERE name IN ('运行中', '已下架', '已报废') ORDER BY sort").fetchall()
    rooms = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    cabinets = db.execute("SELECT * FROM cabinets ORDER BY name").fetchall()
    departments = db.execute("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name").fetchall()
    dept_name = None
    if dept_filter:
        dept = db.execute("SELECT name FROM departments WHERE id=?", (dept_filter,)).fetchone()
        if dept:
            dept_name = dept['name']
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template("devices.html", devices=devices, types=types, states=states, cabinets=cabinets, rooms=rooms,
                           departments=departments, page=page, total_pages=total_pages, total=total,
                           keyword=keyword, type_id=type_id, state_id=state_id, cat_filter=cat_filter,
                           room_filter=room_filter, dept_filter=dept_filter, dept_name=dept_name,
                           warranty_filter=warranty_filter)


@devices_bp.route("/devices/add", methods=["GET", "POST"])
@write_required
def device_add():
    db = get_db()
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in [
            "name", "brand", "model", "serial_number", "biz_ip", "oob_ip",
            "mac_address", "u_position", "location", "custodian",
            "rack_date", "warranty_date", "purchase_price", "remark", "tag",
            "asset_code", "user_name", "depreciation_method"
        ]}
        type_id = request.form.get("device_type_id", type=int)
        state_id = request.form.get("lifecycle_state_id", type=int)
        cabinet_id = request.form.get("cabinet_id", type=int) or None
        room_id = request.form.get("room_id_single", type=int) or None
        department_id = request.form.get("department_id", type=int) or None
        u_height = request.form.get("u_height", 1, type=int)
        quantity = request.form.get("quantity", 1, type=int)
        residual_rate = request.form.get("residual_rate", 5, type=float)
        useful_life = request.form.get("useful_life", 36, type=int)
        software_ids = request.form.getlist("software_ids")
        hardware_ids = request.form.getlist("hardware_ids")
        if u_height not in (1, 2, 4):
            u_height = 1
        if not data["name"] or not type_id or not state_id:
            flash("设备名称、类型、生命周期状态为必填项", "danger")
        else:
            try:
                cur = db.execute("""
                    INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                        biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height, location, custodian,
                        rack_date, warranty_date, purchase_price, lifecycle_state_id, remark, tag, quantity,
                        asset_code, user_name, room_id, department_id, depreciation_method, residual_rate, useful_life, created_by)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (data["name"], type_id, data["brand"], data["model"], data["serial_number"],
                      data["biz_ip"], data["oob_ip"], data["mac_address"], cabinet_id, data["u_position"], u_height,
                      data["location"], data["custodian"], data["rack_date"], data["warranty_date"],
                      float(data["purchase_price"] or 0), state_id, data["remark"], data["tag"], quantity,
                      data["asset_code"], data["user_name"], room_id, department_id, data["depreciation_method"],
                      residual_rate, useful_life, session["user_id"]))
                device_id = cur.lastrowid
                db.execute("INSERT INTO device_logs(device_id, user_id, action, detail) VALUES(?,?,?,?)",
                           (device_id, session["user_id"], "新增设备", f"新增设备: {data['name']}"))
                log_to_db(db, 'INFO', '资产管理', '新增设备', f"新增设备: {data['name']} (类型ID:{type_id})")

                # 保存关联关系
                for sw_id in software_ids:
                    db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                              (device_id, 'device', int(sw_id), 'device', 'runs_on', ''))
                    sw_name = db.execute("SELECT name FROM devices WHERE id=?", (sw_id,)).fetchone()
                    if sw_name:
                        log_to_db(db, 'INFO', '资产管理', '关联软件', f"设备 {data['name']} 关联软件: {sw_name['name']}")
                for hw_id in hardware_ids:
                    db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                              (int(hw_id), 'device', device_id, 'device', 'runs_on', ''))
                    hw_name = db.execute("SELECT name FROM devices WHERE id=?", (hw_id,)).fetchone()
                    if hw_name:
                        log_to_db(db, 'INFO', '资产管理', '关联硬件', f"设备 {data['name']} 关联硬件: {hw_name['name']}")

                db.commit()
                logger.info(f"新增设备: {data['name']} by {session.get('username')}")
                flash("设备添加成功", "success")
                return redirect(url_for("devices.device_list"))
            except Exception as e:
                db.rollback()
                logger.error(f"新增设备失败: {e}")
                flash("新增设备失败，请重试", "danger")
    types = db.execute("SELECT * FROM device_types ORDER BY name").fetchall()
    states = db.execute("SELECT * FROM lifecycle_states WHERE name IN ('运行中', '已下架', '已报废') ORDER BY sort").fetchall()
    rooms = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    cabinets = db.execute("SELECT * FROM cabinets ORDER BY name").fetchall()
    departments = db.execute("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name").fetchall()
    all_software = db.execute("SELECT d.id, d.name, t.name as type_name FROM devices d JOIN device_types t ON d.device_type_id=t.id WHERE t.category='software' ORDER BY d.name").fetchall()
    all_hardware = db.execute("SELECT d.id, d.name, t.name as type_name FROM devices d JOIN device_types t ON d.device_type_id=t.id WHERE t.category='hardware' ORDER BY d.name").fetchall()
    return render_template("device_form.html", device=None, types=types, states=states, rooms=rooms, cabinets=cabinets,
                          departments=departments, all_software=all_software, all_hardware=all_hardware, action="add")


@devices_bp.route("/devices/<int:did>/edit", methods=["GET", "POST"])
@write_required
def device_edit(did):
    db = get_db()
    device = db.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
    if not device:
        abort(404)
    back_url = request.args.get("back", url_for("devices.device_list"))
    if request.method == "POST":
        back_url = request.form.get("back", url_for("devices.device_list"))
        data = {k: request.form.get(k, "").strip() for k in [
            "name", "brand", "model", "serial_number", "biz_ip", "oob_ip",
            "mac_address", "u_position", "location", "custodian",
            "rack_date", "warranty_date", "purchase_price", "remark", "tag",
            "asset_code", "user_name", "depreciation_method"
        ]}
        type_id = request.form.get("device_type_id", type=int)
        state_id = request.form.get("lifecycle_state_id", type=int)
        cabinet_id = request.form.get("cabinet_id", type=int) or None
        room_id = request.form.get("room_id_single", type=int) or None
        department_id = request.form.get("department_id", type=int) or None
        u_height = request.form.get("u_height", 1, type=int)
        quantity = request.form.get("quantity", 1, type=int)
        residual_rate = request.form.get("residual_rate", 5, type=float)
        useful_life = request.form.get("useful_life", 36, type=int)
        software_ids = request.form.getlist("software_ids")
        hardware_ids = request.form.getlist("hardware_ids")
        if u_height not in (1, 2, 4):
            u_height = 1
        old_state = device["lifecycle_state_id"]
        if not data["name"] or not type_id or not state_id:
            flash("设备名称、类型、生命周期状态为必填项", "danger")
        else:
            try:
                db.execute("""
                    UPDATE devices SET name=?, device_type_id=?, brand=?, model=?, serial_number=?,
                        biz_ip=?, oob_ip=?, mac_address=?, cabinet_id=?, u_position=?, u_height=?,
                        location=?, custodian=?,
                        rack_date=?, warranty_date=?, purchase_price=?, lifecycle_state_id=?,
                        remark=?, tag=?, quantity=?, asset_code=?, user_name=?, room_id=?,
                        department_id=?, depreciation_method=?, residual_rate=?, useful_life=?,
                        updated_at=datetime('now','localtime')
                    WHERE id=?
                """, (data["name"], type_id, data["brand"], data["model"], data["serial_number"],
                      data["biz_ip"], data["oob_ip"], data["mac_address"], cabinet_id, data["u_position"], u_height,
                      data["location"], data["custodian"], data["rack_date"], data["warranty_date"],
                      float(data["purchase_price"] or 0), state_id, data["remark"], data["tag"], quantity,
                      data["asset_code"], data["user_name"], room_id, department_id, data["depreciation_method"],
                      residual_rate, useful_life, did))
                if old_state != state_id:
                    old_s = db.execute("SELECT name FROM lifecycle_states WHERE id=?", (old_state,)).fetchone()
                    new_s = db.execute("SELECT name FROM lifecycle_states WHERE id=?", (state_id,)).fetchone()
                    db.execute("INSERT INTO device_logs(device_id, user_id, action, detail) VALUES(?,?,?,?)",
                               (did, session["user_id"], "状态变更", f"{old_s['name']} → {new_s['name']}"))
                db.execute("INSERT INTO device_logs(device_id, user_id, action, detail) VALUES(?,?,?,?)",
                           (did, session["user_id"], "编辑设备", f"更新设备信息: {data['name']}"))
                log_to_db(db, 'INFO', '资产管理', '编辑设备', f"更新设备: {data['name']} (ID:{did})")

                # 更新关联关系：先删除旧的，再插入新的
                old_sw = db.execute("SELECT target_id FROM ci_relationships WHERE source_id=? AND source_type='device' AND target_type='device'", (did,)).fetchall()
                old_sw_ids = {r['target_id'] for r in old_sw}
                old_hw = db.execute("SELECT source_id FROM ci_relationships WHERE target_id=? AND source_type='device' AND target_type='device'", (did,)).fetchall()
                old_hw_ids = {r['source_id'] for r in old_hw}

                db.execute("DELETE FROM ci_relationships WHERE (source_id=? AND source_type='device') OR (target_id=? AND target_type='device')", (did, did))
                for sw_id in software_ids:
                    db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                              (did, 'device', int(sw_id), 'device', 'runs_on', ''))
                    if int(sw_id) not in old_sw_ids:
                        sw_name = db.execute("SELECT name FROM devices WHERE id=?", (sw_id,)).fetchone()
                        if sw_name:
                            log_to_db(db, 'INFO', '资产管理', '新增关联软件', f"设备 {data['name']} 新增关联软件: {sw_name['name']}")
                for hw_id in hardware_ids:
                    db.execute("INSERT INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type, remark) VALUES(?,?,?,?,?,?)",
                              (int(hw_id), 'device', did, 'device', 'runs_on', ''))
                    if int(hw_id) not in old_hw_ids:
                        hw_name = db.execute("SELECT name FROM devices WHERE id=?", (hw_id,)).fetchone()
                        if hw_name:
                            log_to_db(db, 'INFO', '资产管理', '新增关联硬件', f"设备 {data['name']} 新增关联硬件: {hw_name['name']}")

                # 记录删除的关联
                removed_sw = old_sw_ids - {int(s) for s in software_ids}
                for sw_id in removed_sw:
                    sw_name = db.execute("SELECT name FROM devices WHERE id=?", (sw_id,)).fetchone()
                    if sw_name:
                        log_to_db(db, 'INFO', '资产管理', '移除关联软件', f"设备 {data['name']} 移除关联软件: {sw_name['name']}")
                removed_hw = old_hw_ids - {int(h) for h in hardware_ids}
                for hw_id in removed_hw:
                    hw_name = db.execute("SELECT name FROM devices WHERE id=?", (hw_id,)).fetchone()
                    if hw_name:
                        log_to_db(db, 'INFO', '资产管理', '移除关联硬件', f"设备 {data['name']} 移除关联硬件: {hw_name['name']}")

                db.commit()
                logger.info(f"编辑设备: {data['name']} (ID:{did}) by {session.get('username')}")
                flash("设备更新成功", "success")
                return redirect(back_url)
            except Exception as e:
                db.rollback()
                logger.error(f"编辑设备失败: {e}")
                flash("编辑设备失败，请重试", "danger")
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
    
    departments = db.execute("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name").fetchall()
    return render_template("device_form.html", device=device, types=types, states=states, rooms=rooms, cabinets=cabinets,
                          departments=departments, all_software=all_software, all_hardware=all_hardware,
                          device_software=device_software, device_hardware=device_hardware, action="edit", back_url=back_url)


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
    back_url = request.args.get("back", url_for("devices.device_list"))
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

    # 如果是软件资产，计算许可证使用情况
    license_info = None
    if device['category'] == 'software':
        total_licenses = device['quantity'] or 0
        used_licenses = len(hw_list)
        available_licenses = total_licenses - used_licenses
        license_info = {
            'total': total_licenses,
            'used': used_licenses,
            'available': available_licenses,
            'usage_pct': round(used_licenses / total_licenses * 100) if total_licenses > 0 else 0
        }

    # 计算折旧信息
    depreciation_info = None
    if device['purchase_price'] and device['purchase_price'] > 0 and device['depreciation_method'] != 'none':
        from datetime import datetime, date
        purchase_price = device['purchase_price']
        useful_life = device['useful_life'] or 60  # 默认5年
        depreciation_method = device['depreciation_method'] or 'straight_line'

        # 计算已使用月数
        start_date_str = device['rack_date'] or device['created_at'][:10]
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except:
            start_date = date.today()

        today = date.today()
        months_used = (today.year - start_date.year) * 12 + (today.month - start_date.month)
        months_used = max(0, months_used)

        # 五年分摊，满五年残值为0
        residual_value = 0
        depreciable_amount = purchase_price
        monthly_depreciation = depreciable_amount / useful_life if useful_life > 0 else 0

        if depreciation_method == 'straight_line':
            # 直线法
            total_depreciation = min(monthly_depreciation * months_used, depreciable_amount)
            current_value = purchase_price - total_depreciation
        elif depreciation_method == 'declining_balance':
            # 双倍余额递减法
            rate = 2 / useful_life
            remaining = purchase_price
            total_depreciation = 0
            for m in range(min(months_used, useful_life)):
                month_dep = remaining * rate / 12
                total_depreciation += month_dep
                remaining -= month_dep
            total_depreciation = min(total_depreciation, depreciable_amount)
            current_value = purchase_price - total_depreciation
        elif depreciation_method == 'sum_of_years':
            # 年数总和法
            years_sum = useful_life * (useful_life + 1) / 2
            months_used_capped = min(months_used, useful_life)
            total_depreciation = 0
            remaining = purchase_price
            for m in range(months_used_capped):
                year = m // 12
                year_remaining = useful_life - year
                month_dep = depreciable_amount * year_remaining / years_sum / 12
                total_depreciation += month_dep
            total_depreciation = min(total_depreciation, depreciable_amount)
            current_value = purchase_price - total_depreciation
        else:
            total_depreciation = 0
            current_value = purchase_price

        # 满五年后残值为0
        if months_used >= useful_life:
            current_value = 0
            total_depreciation = purchase_price

        total_depreciation = purchase_price - current_value
        remaining_months = max(0, useful_life - months_used)

        # 折旧到期日期
        try:
            dep_end_date = date(start_date.year + useful_life // 12, start_date.month + useful_life % 12, 1)
        except:
            dep_end_date = date(start_date.year + useful_life // 12 + 1, 1, 1)

        depreciation_info = {
            'method': depreciation_method,
            'method_name': {'straight_line': '直线法', 'declining_balance': '双倍余额递减法', 'sum_of_years': '年数总和法'}.get(depreciation_method, '未知'),
            'purchase_price': purchase_price,
            'residual_rate': 0,
            'residual_value': 0,
            'depreciable_amount': round(depreciable_amount, 2),
            'useful_life': useful_life,
            'months_used': months_used,
            'remaining_months': remaining_months,
            'monthly_depreciation': round(monthly_depreciation, 2),
            'total_depreciation': round(total_depreciation, 2),
            'current_value': round(current_value, 2),
            'dep_end_date': dep_end_date.strftime('%Y-%m-%d') if isinstance(dep_end_date, date) else str(dep_end_date),
            'dep_progress': round(min(months_used, useful_life) / useful_life * 100, 1) if useful_life > 0 else 100,
        }

    return render_template("device_detail.html", device=device, logs=logs, systems=systems,
                          software_assets=sw_list, hardware_assets=hw_list,
                          license_info=license_info, depreciation_info=depreciation_info, back_url=back_url)


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
                log_to_db(db, 'INFO', '设备类型', '新增类型', f"新增设备类型: {name} (分类:{category})")
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
        type_name = db.execute("SELECT name FROM device_types WHERE id=?", (tid,)).fetchone()
        db.execute("DELETE FROM device_types WHERE id=?", (tid,))
        db.commit()
        if type_name:
            log_to_db(db, 'WARNING', '设备类型', '删除类型', f"删除设备类型: {type_name['name']}")
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
    log_to_db(db, 'INFO', '资产管理', '批量编辑', f"批量修改 {len(ids)} 台设备")
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
    log_to_db(db, 'WARNING', '资产管理', '批量删除', f"批量删除 {len(ids)} 台设备")
    flash(f"成功删除 {len(ids)} 台设备", "success")
    return redirect(url_for("devices.device_list"))
