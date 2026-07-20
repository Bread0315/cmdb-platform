"""
CMDB Platform - 机房机柜管理
"""
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
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
        name = request.form.get("name", "").strip()
        u_total = request.form.get("u_total", 42, type=int)
        power = request.form.get("power", "").strip()
        remark = request.form.get("remark", "").strip()
        if not name:
            flash("机柜名称为必填项", "danger")
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
    # 只显示运行中的设备
    devices = db.execute("""
        SELECT d.id, d.name, d.u_position, d.u_height, t.name as type_name, s.name as state_name,
               d.biz_ip, d.oob_ip, d.custodian
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE d.cabinet_id=? AND d.u_position != '' AND s.name = '运行中'
        ORDER BY d.u_position
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

    return render_template("cabinet_rack.html", cabinet=cabinet, devices=devices, u_map=u_map,
                           gap_positions=gap_positions, start_positions=start_positions, end_positions=end_positions)
