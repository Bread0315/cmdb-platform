"""
CMDB Platform - 机房机柜管理
"""
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify
from auth import login_required, write_required
from db import get_db, log_to_db
from config import logger

rooms_bp = Blueprint('rooms', __name__)


@rooms_bp.route("/rooms")
@login_required
def room_list():
    db = get_db()
    rooms = db.execute("""
        SELECT r.*,
            (SELECT COUNT(*) FROM cabinets WHERE room_id=r.id) as cabinet_count,
            (SELECT COUNT(*) FROM devices d JOIN cabinets c ON d.cabinet_id=c.id
             JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
             WHERE c.room_id=r.id AND s.name NOT IN ('已下架','已报废')) as device_count
        FROM rooms r ORDER BY r.name
    """).fetchall()
    return render_template("rooms.html", rooms=rooms)


@rooms_bp.route("/rooms/add", methods=["GET", "POST"])
@write_required
def room_add():
    if request.method == "POST":
        db = get_db()
        data = {k: request.form.get(k, "").strip() for k in ["name", "building", "floor", "location", "remark"]}
        if not data["name"]:
            flash("机房名称为必填项", "danger")
        else:
            db.execute("INSERT INTO rooms(name, building, floor, location, remark) VALUES(?,?,?,?,?)",
                       (data["name"], data["building"], data["floor"], data["location"], data["remark"]))
            log_to_db(db, 'INFO', '机房管理', '新增机房', f"新增机房: {data['name']}")
            db.commit()
            logger.info(f"新增机房: {data['name']} by {session.get('username')}")
            flash("机房添加成功", "success")
            return redirect(url_for("rooms.room_list"))
    return render_template("room_form.html", room=None, action="add")


@rooms_bp.route("/rooms/<int:rid>/edit", methods=["GET", "POST"])
@write_required
def room_edit(rid):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
    if not room:
        abort(404)
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in ["name", "building", "floor", "location", "remark"]}
        if not data["name"]:
            flash("机房名称为必填项", "danger")
        else:
            db.execute("UPDATE rooms SET name=?, building=?, floor=?, location=?, remark=? WHERE id=?",
                       (data["name"], data["building"], data["floor"], data["location"], data["remark"], rid))
            log_to_db(db, 'INFO', '机房管理', '编辑机房', f"更新机房: {data['name']}")
            db.commit()
            flash("机房信息已更新", "success")
            return redirect(url_for("rooms.room_list"))
    return render_template("room_form.html", room=room, action="edit")


@rooms_bp.route("/rooms/<int:rid>/delete", methods=["POST"])
@write_required
def room_delete(rid):
    db = get_db()
    room = db.execute("SELECT name FROM rooms WHERE id=?", (rid,)).fetchone()
    if not room:
        abort(404)
    cab_count = db.execute("SELECT COUNT(*) FROM cabinets WHERE room_id=?", (rid,)).fetchone()[0]
    if cab_count > 0:
        flash(f"该机房下有机柜 {cab_count} 个，请先删除机柜", "danger")
        return redirect(url_for("rooms.room_list"))
    db.execute("DELETE FROM rooms WHERE id=?", (rid,))
    log_to_db(db, 'WARNING', '机房管理', '删除机房', f"删除机房: {room['name']}")
    db.commit()
    logger.warning(f"删除机房: {room['name']} by {session.get('username')}")
    flash("机房已删除", "success")
    return redirect(url_for("rooms.room_list"))


@rooms_bp.route("/cabinets")
@login_required
def all_cabinets():
    """显示所有机柜"""
    db = get_db()
    cabinets = db.execute("""
        SELECT c.*, r.name as room_name,
            (SELECT COUNT(*) FROM devices d
             JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
             WHERE d.cabinet_id=c.id AND s.name NOT IN ('已下架', '已报废')) as device_count
        FROM cabinets c
        LEFT JOIN rooms r ON c.room_id=r.id
        ORDER BY r.name, c.name
    """).fetchall()
    return render_template("all_cabinets.html", cabinets=cabinets)


@rooms_bp.route("/rooms/<int:rid>/cabinets")
@login_required
def room_cabinets(rid):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
    if not room:
        abort(404)
    cabinets = db.execute("""
        SELECT c.*,
            (SELECT COUNT(*) FROM devices d
             JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
             WHERE d.cabinet_id=c.id AND s.name NOT IN ('已下架', '已报废')) as device_count
        FROM cabinets c WHERE c.room_id=? ORDER BY c.name
    """, (rid,)).fetchall()
    return render_template("room_cabinets.html", room=room, cabinets=cabinets)


@rooms_bp.route("/rooms/<int:rid>/cabinets/add", methods=["GET", "POST"])
@write_required
def room_cabinet_add(rid):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
    if not room:
        abort(404)
    if request.method == "POST":
        # 批量添加模式
        batch_mode = request.form.get("batch_mode", "")
        if batch_mode == "1":
            names = request.form.get("names", "").strip()
            prefix = request.form.get("prefix", "").strip()
            start_num = request.form.get("start_num", 1, type=int)
            count = request.form.get("count", 1, type=int)
            u_total = request.form.get("u_total", 42, type=int)
            power = request.form.get("power", "").strip() or "双路市电 220V 16A"
            remark = request.form.get("remark", "").strip()

            if names:
                # 按名称列表批量添加
                name_list = [n.strip() for n in names.split('\n') if n.strip()]
                for name in name_list:
                    db.execute("INSERT INTO cabinets(room_id, name, u_total, power, remark) VALUES(?,?,?,?,?)",
                               (rid, name, u_total, power, remark))
                    log_to_db(db, 'INFO', '机柜管理', '新增机柜', f"新增机柜: {name} (机房ID:{rid})")
                db.commit()
                flash(f"成功添加 {len(name_list)} 个机柜", "success")
            elif prefix:
                import re
                # 检查已有机柜名
                existing = {r[0] for r in db.execute("SELECT name FROM cabinets WHERE room_id=?", (rid,)).fetchall()}

                # 解析前缀格式：支持 "C1-10" → C1,C2,...,C10 或 "RACK-" + 编号
                range_match = re.match(r'^(.+)-(\d+)$', prefix)
                if range_match:
                    # 范围格式：前缀-结束编号，从1开始
                    base = range_match.group(1)
                    end_num = int(range_match.group(2))
                    added = 0
                    skipped = []
                    for i in range(1, end_num + 1):
                        name = f"{base}{i}"
                        if name in existing:
                            skipped.append(name)
                            continue
                        db.execute("INSERT INTO cabinets(room_id, name, u_total, power, remark) VALUES(?,?,?,?,?)",
                                   (rid, name, u_total, power, remark))
                        log_to_db(db, 'INFO', '机柜管理', '新增机柜', f"新增机柜: {name} (机房ID:{rid})")
                        added += 1
                    db.commit()
                    if skipped:
                        flash(f"添加 {added} 个机柜，跳过重复: {', '.join(skipped)}", "warning")
                    else:
                        flash(f"成功添加 {added} 个机柜", "success")
                else:
                    # 普通前缀格式：前缀 + 编号
                    added = 0
                    skipped = []
                    for i in range(count):
                        name = f"{prefix}{start_num + i}"
                        if name in existing:
                            skipped.append(name)
                            continue
                        db.execute("INSERT INTO cabinets(room_id, name, u_total, power, remark) VALUES(?,?,?,?,?)",
                                   (rid, name, u_total, power, remark))
                        log_to_db(db, 'INFO', '机柜管理', '新增机柜', f"新增机柜: {name} (机房ID:{rid})")
                        added += 1
                    db.commit()
                    if skipped:
                        flash(f"添加 {added} 个机柜，跳过重复: {', '.join(skipped)}", "warning")
                    else:
                        flash(f"成功添加 {added} 个机柜", "success")
            else:
                flash("请填写机柜名称或前缀", "danger")
                return render_template("cabinet_form.html", room=room, cabinet=None, action="add")
        else:
            # 单个添加模式
            name = request.form.get("name", "").strip()
            u_total = request.form.get("u_total", 42, type=int)
            power = request.form.get("power", "").strip() or "双路市电 220V 16A"
            remark = request.form.get("remark", "").strip()
            if not name:
                flash("机柜名称为必填项", "danger")
            else:
                exists = db.execute("SELECT id FROM cabinets WHERE room_id=? AND name=?", (rid, name)).fetchone()
                if exists:
                    flash(f"机柜名称 '{name}' 在该机房已存在", "danger")
                else:
                    db.execute("INSERT INTO cabinets(room_id, name, u_total, power, remark) VALUES(?,?,?,?,?)",
                               (rid, name, u_total, power, remark))
                    log_to_db(db, 'INFO', '机柜管理', '新增机柜', f"新增机柜: {name} (机房ID:{rid})")
                    db.commit()
                    flash("机柜添加成功", "success")
        return redirect(url_for("rooms.room_cabinets", rid=rid))
    return render_template("cabinet_form.html", room=room, cabinet=None, action="add")


@rooms_bp.route("/cabinets/<int:cid>/edit", methods=["GET", "POST"])
@write_required
def cabinet_edit(cid):
    db = get_db()
    cabinet = db.execute("SELECT c.*, r.name as room_name FROM cabinets c LEFT JOIN rooms r ON c.room_id=r.id WHERE c.id=?", (cid,)).fetchone()
    if not cabinet:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        u_total = request.form.get("u_total", 42, type=int)
        power = request.form.get("power", "").strip()
        remark = request.form.get("remark", "").strip()
        if not name:
            flash("机柜名称为必填项", "danger")
        else:
            db.execute("UPDATE cabinets SET name=?, u_total=?, power=?, remark=? WHERE id=?",
                       (name, u_total, power, remark, cid))
            log_to_db(db, 'INFO', '机柜管理', '编辑机柜', f"更新机柜: {name}")
            db.commit()
            flash("机柜信息已更新", "success")
            return redirect(url_for("rooms.room_cabinets", rid=cabinet['room_id']))
    return render_template("cabinet_form.html", room=None, cabinet=cabinet, action="edit")


@rooms_bp.route("/cabinets/<int:cid>/delete", methods=["POST"])
@write_required
def cabinet_delete(cid):
    db = get_db()
    cabinet = db.execute("SELECT name, room_id FROM cabinets WHERE id=?", (cid,)).fetchone()
    if not cabinet:
        abort(404)
    db.execute("DELETE FROM cabinets WHERE id=?", (cid,))
    log_to_db(db, 'WARNING', '机柜管理', '删除机柜', f"删除机柜: {cabinet['name']}")
    db.commit()
    logger.warning(f"删除机柜: {cabinet['name']} by {session.get('username')}")
    flash("机柜已删除", "success")
    return redirect(url_for("rooms.room_cabinets", rid=cabinet['room_id']))


@rooms_bp.route("/cabinets/<int:cid>/rack")
@login_required
def cabinet_rack(cid):
    db = get_db()
    cabinet = db.execute("SELECT c.*, r.name as room_name FROM cabinets c LEFT JOIN rooms r ON c.room_id=r.id WHERE c.id=?", (cid,)).fetchone()
    if not cabinet:
        abort(404)
    # 只显示运行中的设备（有U位的，用于机柜图展示）
    devices = db.execute("""
        SELECT d.id, d.name, d.u_position, d.u_height, t.name as type_name, s.name as state_name,
               d.biz_ip, d.oob_ip, d.custodian
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE d.cabinet_id=? AND d.u_position != '' AND s.name = '运行中'
        ORDER BY d.u_position
    """, (cid,)).fetchall()

    # 未分配机柜的硬件设备（用于U位分配）
    unassigned_devices = db.execute("""
        SELECT d.id, d.name, d.u_height, t.name as type_name, t.category
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        LEFT JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE (d.cabinet_id IS NULL OR d.cabinet_id = '')
        AND t.category IN ('hardware', 'network')
        AND s.name = '运行中'
        ORDER BY d.name
    """).fetchall()

    # 该机柜已有设备（用于调整位置）
    cabinet_devices = db.execute("""
        SELECT d.id, d.name, d.u_position, d.u_height, t.name as type_name
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        WHERE d.cabinet_id=?
        ORDER BY d.name
    """, (cid,)).fetchall()

    # 解析 U 位占用，支持多 U 高度设备
    u_map = {}
    device_ranges = []
    for d in devices:
        pos = d['u_position'].strip().upper()
        height = d['u_height'] or 1
        m = re.match(r'U?(\d+)(?:\s*[-–]\s*U?(\d+))?U?$', pos)
        if m:
            u1 = int(m.group(1))
            u2 = int(m.group(2)) if m.group(2) else u1
            # 确保 start <= end（支持 U42-U41 这种降序写法）
            start_u = min(u1, u2)
            end_u = max(u1, u2)
            device_ranges.append((start_u, end_u, d))
            for u in range(start_u, min(end_u + 1, cabinet['u_total'] + 1)):
                u_map[u] = d

    gap_positions = set()
    start_positions = {}
    end_positions = {}
    for start_u, end_u, d in device_ranges:
        start_positions[d['id']] = start_u
        end_positions[d['id']] = end_u
        gap_u = start_u - 1
        if gap_u >= 1 and gap_u not in u_map:
            gap_positions.add(gap_u)

    # 构建已占用U位列表
    occupied_u = list(u_map.keys())

    return render_template("cabinet_rack.html", cabinet=cabinet, devices=devices,
                           unassigned_devices=unassigned_devices, cabinet_devices=cabinet_devices,
                           u_map=u_map, gap_positions=gap_positions,
                           start_positions=start_positions, end_positions=end_positions,
                           occupied_u=occupied_u)


@rooms_bp.route("/rooms/<int:rid>/cabinets/batch-edit", methods=["POST"])
@write_required
def cabinet_batch_edit(rid):
    db = get_db()
    ids_str = request.form.get("ids", "").strip()
    if not ids_str:
        flash("请选择机柜", "danger")
        return redirect(url_for("rooms.room_cabinets", rid=rid))

    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        flash("无效的机柜ID", "danger")
        return redirect(url_for("rooms.room_cabinets", rid=rid))

    u_total = request.form.get("u_total", "").strip()
    power = request.form.get("power", "").strip()

    placeholders = ','.join('?' * len(ids))
    updates = []
    params = []

    if u_total:
        updates.append("u_total=?")
        params.append(int(u_total))
    if power:
        updates.append("power=?")
        params.append(power)

    if updates:
        sql = f"UPDATE cabinets SET {', '.join(updates)} WHERE id IN ({placeholders})"
        db.execute(sql, params + ids)
        db.commit()
        log_to_db(db, 'INFO', '机柜管理', '批量编辑', f"批量编辑 {len(ids)} 个机柜")
        flash(f"成功修改 {len(ids)} 个机柜", "success")
    else:
        flash("未修改任何内容", "warning")

    return redirect(url_for("rooms.room_cabinets", rid=rid))


@rooms_bp.route("/rooms/<int:rid>/cabinets/batch-delete", methods=["POST"])
@write_required
def cabinet_batch_delete(rid):
    db = get_db()
    data = request.get_json()
    if not data or "ids" not in data:
        return jsonify({"success": False, "message": "无效请求"})

    ids = data["ids"]
    if not ids:
        return jsonify({"success": False, "message": "请选择机柜"})

    # 检查是否有设备的机柜
    placeholders = ','.join('?' * len(ids))
    occupied = db.execute(f"""
        SELECT c.name FROM cabinets c
        WHERE c.id IN ({placeholders}) AND EXISTS (
            SELECT 1 FROM devices d WHERE d.cabinet_id=c.id
        )
    """, ids).fetchall()

    if occupied:
        names = [r['name'] for r in occupied]
        return jsonify({"success": False, "message": f"以下机柜有设备，无法删除: {', '.join(names)}"})

    db.execute(f"DELETE FROM cabinets WHERE id IN ({placeholders})", ids)
    db.commit()
    log_to_db(db, 'WARNING', '机柜管理', '批量删除', f"批量删除 {len(ids)} 个机柜")
    return jsonify({"success": True})


@rooms_bp.route("/api/cabinets/<int:cid>/update-position", methods=["POST"])
@login_required
def update_device_position(cid):
    """更新设备在机柜中的U位"""
    db = get_db()
    data = request.get_json()
    if not data or "device_id" not in data or "u_position" not in data:
        return jsonify({"success": False, "message": "参数错误"})

    device_id = data["device_id"]
    u_position = data["u_position"].strip()

    device = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    if not device:
        return jsonify({"success": False, "message": "设备不存在"})

    # 检查设备是否属于这个机柜（允许未分配的设备移入）
    device_cabinet = device["cabinet_id"]
    if device_cabinet and device_cabinet != cid:
        return jsonify({"success": False, "message": "设备已分配到其他机柜，请先移出"})

    # 如果清空U位，移出机柜
    if not u_position:
        db.execute("UPDATE devices SET u_position='', cabinet_id=NULL WHERE id=?", (device_id,))
        db.commit()
        log_to_db(db, 'INFO', '机柜管理', '移出机柜', f"设备 {device['name']} 移出机柜")
        return jsonify({"success": True})

    # 检查U位格式
    import re
    m = re.match(r'^U?(\d+)(?:\s*[-–]\s*U?(\d+))?$', u_position.upper())
    if not m:
        return jsonify({"success": False, "message": "U位格式错误，如：U10 或 U10-U12"})

    u1 = int(m.group(1))
    u2 = int(m.group(2)) if m.group(2) else u1
    start_u = min(u1, u2)
    end_u = max(u1, u2)

    # 检查U位范围
    cabinet = db.execute("SELECT * FROM cabinets WHERE id=?", (cid,)).fetchone()
    if end_u > cabinet["u_total"]:
        return jsonify({"success": False, "message": f"U位超出机柜总容量 {cabinet['u_total']}U"})

    # 检查U位是否被占用（排除当前设备）
    # 获取该机柜所有设备的U位占用情况
    occupied_devices = db.execute("""
        SELECT d.id, d.name, d.u_position FROM devices d
        WHERE d.cabinet_id=? AND d.u_position != '' AND d.id != ?
    """, (cid, device_id)).fetchall()

    for od in occupied_devices:
        pos = od['u_position'].upper().replace('U', '').replace('–', '-').replace(' ', '-')
        parts = pos.split('-')
        try:
            od_start = int(parts[0])
            od_end = int(parts[1]) if len(parts) > 1 else od_start
        except (ValueError, IndexError):
            continue
        # 检查是否有重叠
        if start_u <= od_end and end_u >= od_start:
            return jsonify({"success": False, "message": f"U位冲突：{od['name']} 占用 U{od_start}-U{od_end}"})

    # 更新U位和机柜
    formatted_pos = f"U{start_u}" if start_u == end_u else f"U{start_u}-U{end_u}"
    db.execute("UPDATE devices SET u_position=?, cabinet_id=? WHERE id=?", (formatted_pos, cid, device_id))
    db.commit()
    action = "分配到机柜" if not device_cabinet else "调整U位"
    log_to_db(db, 'INFO', '机柜管理', action, f"设备 {device['name']} {action} {formatted_pos}")
    return jsonify({"success": True})
