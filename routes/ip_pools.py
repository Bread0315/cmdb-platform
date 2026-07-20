"""
CMDB Platform - IP 地址池管理（多网段版）
"""
import ipaddress
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from auth import login_required, write_required
from db import get_db, log_to_db
from config import logger

ip_pools_bp = Blueprint('ip_pools', __name__)


def ip_to_int(ip_str):
    parts = ip_str.strip().split('.')
    if len(parts) != 4:
        return None
    try:
        return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])
    except ValueError:
        return None


def int_to_ip(num):
    return f"{(num >> 24) & 0xFF}.{(num >> 16) & 0xFF}.{(num >> 8) & 0xFF}.{num & 0xFF}"


def cidr_to_range(network, mask):
    net = ipaddress.IPv4Network(f"{network}/{mask}", strict=False)
    hosts = list(net.hosts())
    if hosts:
        return str(hosts[0]), str(hosts[-1])
    return network, network


def sync_segment(db, segment_id):
    """同步单个网段的 IP 地址"""
    seg = db.execute("SELECT * FROM ip_pool_segments WHERE id=?", (segment_id,)).fetchone()
    if not seg:
        return
    pool_id = seg[1] if isinstance(seg, tuple) else seg['pool_id']
    network = seg[2] if isinstance(seg, tuple) else seg['network']
    mask = seg[3] if isinstance(seg, tuple) else seg['mask']
    gateway = (seg[4] or '') if isinstance(seg, tuple) else (seg['gateway'] or '')

    start_ip, end_ip = cidr_to_range(network, mask)
    start_int = ip_to_int(start_ip)
    end_int = ip_to_int(end_ip)
    if start_int is None or end_int is None:
        return

    existing = {row[0] for row in db.execute("SELECT ip FROM ip_addresses WHERE pool_id=?", (pool_id,)).fetchall()}

    for ip_int in range(start_int, end_int + 1):
        ip_str = int_to_ip(ip_int)
        if ip_str not in existing:
            status = 'gateway' if ip_str == gateway else 'available'
            db.execute("INSERT INTO ip_addresses(pool_id, ip, status) VALUES(?,?,?)",
                       (pool_id, ip_str, status))


def sync_pool(db, pool_id):
    """同步地址池下所有网段的 IP"""
    segments = db.execute("SELECT id FROM ip_pool_segments WHERE pool_id=?", (pool_id,)).fetchall()
    for seg in segments:
        seg_id = seg[0] if isinstance(seg, tuple) else seg['id']
        sync_segment(db, seg_id)


def sync_all_ip_pools(db):
    """同步所有地址池"""
    pools = db.execute("SELECT id FROM ip_pools").fetchall()
    for p in pools:
        pid = p[0] if isinstance(p, tuple) else p['id']
        sync_pool(db, pid)


@ip_pools_bp.route("/ip-pools")
@login_required
def ip_pool():
    db = get_db()
    room_id = request.args.get('room_id', '', type=str)
    keyword = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    # 构建查询
    conditions = []
    params = []
    if room_id:
        conditions.append("p.id IN (SELECT pool_id FROM ip_pool_segments WHERE room_id=?)")
        params.append(int(room_id))
    if keyword:
        conditions.append("p.name LIKE ?")
        params.append(f"%{keyword}%")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # 总数
    total = db.execute(f"SELECT COUNT(*) FROM ip_pools p {where_clause}", params).fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    pools = db.execute(f"""
        SELECT p.*,
            (SELECT COUNT(*) FROM ip_addresses WHERE pool_id=p.id AND status='used') as used_ips,
            (SELECT COUNT(*) FROM ip_addresses WHERE pool_id=p.id) as total_ips,
            (SELECT COUNT(*) FROM ip_pool_segments WHERE pool_id=p.id) as segment_count,
            u.username as creator_name
        FROM ip_pools p LEFT JOIN users u ON p.created_by=u.id
        {where_clause}
        ORDER BY p.created_at DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()

    # 获取每个池的网段列表
    pool_segments = {}
    for p in pools:
        segs = db.execute("""
            SELECT s.*, r.name as room_name
            FROM ip_pool_segments s
            LEFT JOIN rooms r ON s.room_id = r.id
            WHERE s.pool_id=? ORDER BY s.network
        """, (p['id'],)).fetchall()
        pool_segments[p['id']] = segs

    rooms = db.execute("SELECT id, name FROM rooms ORDER BY name").fetchall()
    return render_template("ip_pools.html", pools=pools, pool_segments=pool_segments,
                           rooms=rooms, room_id=room_id, keyword=keyword,
                           page=page, total_pages=total_pages, total=total)


@ip_pools_bp.route("/ip-pools/add", methods=["GET", "POST"])
@write_required
def ip_pool_add():
    db = get_db()
    rooms = db.execute("SELECT id, name FROM rooms ORDER BY name").fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        remark = request.form.get("remark", "").strip()
        # 获取网段列表
        networks = request.form.getlist("segment_network[]")
        masks = request.form.getlist("segment_mask[]")
        gateways = request.form.getlist("segment_gateway[]")
        vlans = request.form.getlist("segment_vlan[]")
        room_ids = request.form.getlist("segment_room_id[]")
        segRemarks = request.form.getlist("segment_remark[]")

        if not name:
            flash("地址池名称不能为空", "danger")
        elif not networks or not any(n.strip() for n in networks):
            flash("至少需要一个网段", "danger")
        else:
            # 检查 VLAN 唯一性
            vlans_stripped = [v.strip() for v in vlans if v.strip()]
            for vl in vlans_stripped:
                existing = db.execute("SELECT id FROM ip_pool_segments WHERE vlan=?", (vl,)).fetchone()
                if existing:
                    flash(f"VLAN {vl} 已被使用", "danger")
                    return render_template("ip_pool_form.html", pool=None, rooms=rooms, action="add")

            cur = db.execute("INSERT INTO ip_pools(name, remark, created_by) VALUES(?,?,?)",
                           (name, remark, session["user_id"]))
            pool_id = cur.lastrowid
            for i in range(len(networks)):
                net = networks[i].strip()
                if not net:
                    continue
                try:
                    mask = int(masks[i]) if masks[i] else 24
                except (ValueError, IndexError):
                    mask = 24
                gw = gateways[i].strip() if i < len(gateways) else ''
                vl = vlans[i].strip() if i < len(vlans) else ''
                sr = segRemarks[i].strip() if i < len(segRemarks) else ''
                rid = int(room_ids[i]) if i < len(room_ids) and room_ids[i] else None
                db.execute(
                    "INSERT INTO ip_pool_segments(pool_id, network, mask, gateway, vlan, room_id, remark) VALUES(?,?,?,?,?,?,?)",
                    (pool_id, net, mask, gw, vl, rid, sr)
                )
            sync_pool(db, pool_id)
            log_to_db(db, 'INFO', 'IP管理', '新增地址池', f"新增地址池: {name}")
            db.commit()
            flash("IP 地址池创建成功", "success")
            return redirect(url_for("ip_pools.ip_pool"))
    return render_template("ip_pool_form.html", pool=None, rooms=rooms, action="add")


@ip_pools_bp.route("/ip-pools/<int:pid>/edit", methods=["GET", "POST"])
@write_required
def ip_pool_edit(pid):
    db = get_db()
    pool = db.execute("SELECT * FROM ip_pools WHERE id=?", (pid,)).fetchone()
    if not pool:
        abort(404)
    rooms = db.execute("SELECT id, name FROM rooms ORDER BY name").fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        remark = request.form.get("remark", "").strip()
        networks = request.form.getlist("segment_network[]")
        masks = request.form.getlist("segment_mask[]")
        gateways = request.form.getlist("segment_gateway[]")
        vlans = request.form.getlist("segment_vlan[]")
        room_ids = request.form.getlist("segment_room_id[]")
        segRemarks = request.form.getlist("segment_remark[]")
        segIds = request.form.getlist("segment_id[]")

        if not name:
            flash("地址池名称不能为空", "danger")
        elif not networks or not any(n.strip() for n in networks):
            flash("至少需要一个网段", "danger")
        else:
            # 检查 VLAN 唯一性（排除当前池的网段）
            vlans_stripped = [v.strip() for v in vlans if v.strip()]
            for vl in vlans_stripped:
                existing = db.execute("SELECT id, pool_id FROM ip_pool_segments WHERE vlan=?", (vl,)).fetchone()
                if existing and existing['pool_id'] != pid:
                    flash(f"VLAN {vl} 已被其他地址池使用", "danger")
                    segments = db.execute("SELECT * FROM ip_pool_segments WHERE pool_id=? ORDER BY network", (pid,)).fetchall()
                    return render_template("ip_pool_form.html", pool=pool, segments=segments, rooms=rooms, action="edit")

            db.execute("UPDATE ip_pools SET name=?, remark=? WHERE id=?", (name, remark, pid))

            # 收集表单中的网段
            form_segs = {}
            for i in range(len(networks)):
                net = networks[i].strip()
                if not net:
                    continue
                try:
                    mask = int(masks[i]) if masks[i] else 24
                except (ValueError, IndexError):
                    mask = 24
                gw = gateways[i].strip() if i < len(gateways) else ''
                vl = vlans[i].strip() if i < len(vlans) else ''
                sr = segRemarks[i].strip() if i < len(segRemarks) else ''
                rid = int(room_ids[i]) if i < len(room_ids) and room_ids[i] else None
                sid = segIds[i] if i < len(segIds) and segIds[i] else None
                form_segs[(net, mask)] = {'gateway': gw, 'vlan': vl, 'room_id': rid, 'remark': sr, 'id': sid}

            # 已有网段
            existing_segs = db.execute("SELECT * FROM ip_pool_segments WHERE pool_id=?", (pid,)).fetchall()
            existing_keys = {(s['network'], s['mask']): s for s in existing_segs}

            # 删除不再存在的网段
            for key, seg in existing_keys.items():
                if key not in form_segs:
                    db.execute("DELETE FROM ip_pool_segments WHERE id=?", (seg['id'],))

            # 更新或新增网段
            for key, data in form_segs.items():
                if key in existing_keys:
                    old = existing_keys[key]
                    if (old['gateway'] != data['gateway'] or old['vlan'] != data['vlan'] or
                        old['room_id'] != data['room_id'] or old['remark'] != data['remark']):
                        db.execute("UPDATE ip_pool_segments SET gateway=?, vlan=?, room_id=?, remark=? WHERE id=?",
                                  (data['gateway'], data['vlan'], data['room_id'], data['remark'], old['id']))
                else:
                    db.execute(
                        "INSERT INTO ip_pool_segments(pool_id, network, mask, gateway, vlan, room_id, remark) VALUES(?,?,?,?,?,?,?)",
                        (pid, key[0], key[1], data['gateway'], data['vlan'], data['room_id'], data['remark'])
                    )

            sync_pool(db, pid)
            log_to_db(db, 'INFO', 'IP管理', '编辑地址池', f"编辑地址池: {name}")
            db.commit()
            flash("地址池更新成功", "success")
            return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))

    segments = db.execute("SELECT * FROM ip_pool_segments WHERE pool_id=? ORDER BY network", (pid,)).fetchall()
    return render_template("ip_pool_form.html", pool=pool, segments=segments, rooms=rooms, action="edit")


@ip_pools_bp.route("/ip-pools/<int:pid>/delete", methods=["POST"])
@write_required
def ip_pool_delete(pid):
    db = get_db()
    pool = db.execute("SELECT name FROM ip_pools WHERE id=?", (pid,)).fetchone()
    if not pool:
        abort(404)
    db.execute("DELETE FROM ip_pools WHERE id=?", (pid,))
    log_to_db(db, 'WARNING', 'IP管理', '删除地址池', f"删除地址池: {pool['name']}")
    db.commit()
    flash("IP 地址池已删除", "success")
    return redirect(url_for("ip_pools.ip_pool"))


@ip_pools_bp.route("/ip-pools/<int:pid>/segments/add", methods=["POST"])
@write_required
def segment_add(pid):
    db = get_db()
    pool = db.execute("SELECT * FROM ip_pools WHERE id=?", (pid,)).fetchone()
    if not pool:
        abort(404)
    network = request.form.get("network", "").strip()
    mask_str = request.form.get("mask", "24").strip()
    gateway = request.form.get("gateway", "").strip()
    vlan = request.form.get("vlan", "").strip()
    room_id = request.form.get("room_id", "").strip()
    remark = request.form.get("remark", "").strip()
    if not network:
        flash("网络地址不能为空", "danger")
    else:
        # 检查 VLAN 唯一性
        if vlan:
            existing = db.execute("SELECT id FROM ip_pool_segments WHERE vlan=?", (vlan,)).fetchone()
            if existing:
                flash(f"VLAN {vlan} 已被使用", "danger")
                return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))
        try:
            mask = int(mask_str)
        except ValueError:
            mask = 24
        rid = int(room_id) if room_id else None
        try:
            db.execute(
                "INSERT INTO ip_pool_segments(pool_id, network, mask, gateway, vlan, room_id, remark) VALUES(?,?,?,?,?,?,?)",
                (pid, network, mask, gateway, vlan, rid, remark)
            )
            # 找到刚插入的 segment
            seg = db.execute("SELECT id FROM ip_pool_segments WHERE pool_id=? AND network=? AND mask=?",
                           (pid, network, mask)).fetchone()
            if seg:
                sync_segment(db, seg['id'])
            log_to_db(db, 'INFO', 'IP管理', '新增网段', f"地址池 {pool['name']} 新增网段: {network}/{mask}")
            db.commit()
            flash(f"网段 {network}/{mask} 添加成功", "success")
        except Exception as e:
            flash(f"添加失败: {e}", "danger")
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))


@ip_pools_bp.route("/ip-pools/<int:pid>/segments/<int:sid>/delete", methods=["POST"])
@write_required
def segment_delete(pid, sid):
    db = get_db()
    seg = db.execute("SELECT * FROM ip_pool_segments WHERE id=? AND pool_id=?", (sid, pid)).fetchone()
    if not seg:
        abort(404)

    # 检查该网段下是否有使用中的 IP
    start_ip, end_ip = cidr_to_range(seg['network'], seg['mask'])
    used_count = db.execute("""
        SELECT COUNT(*) FROM ip_addresses
        WHERE pool_id=? AND ip >= ? AND ip <= ? AND status='used'
    """, (pid, start_ip, end_ip)).fetchone()[0]

    if used_count > 0:
        flash(f"该网段有 {used_count} 个 IP 正在使用中，无法删除。请先释放所有已分配的 IP。", "danger")
        return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))

    # 删除该网段下的 IP（仅删除该网段范围内的）
    db.execute("DELETE FROM ip_addresses WHERE pool_id=? AND ip >= ? AND ip <= ?",
               (pid, start_ip, end_ip))
    db.execute("DELETE FROM ip_pool_segments WHERE id=?", (sid,))
    log_to_db(db, 'WARNING', 'IP管理', '删除网段', f"删除网段: {seg['network']}/{seg['mask']}")
    db.commit()
    flash("网段已删除", "success")
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))


@ip_pools_bp.route("/ip-pools/<int:pid>")
@login_required
def ip_pool_detail(pid):
    db = get_db()
    pool = db.execute("SELECT * FROM ip_pools WHERE id=?", (pid,)).fetchone()
    if not pool:
        abort(404)

    # 获取网段列表
    segments = db.execute("""
        SELECT s.*, r.name as room_name
        FROM ip_pool_segments s
        LEFT JOIN rooms r ON s.room_id = r.id
        WHERE s.pool_id=? ORDER BY s.network
    """, (pid,)).fetchall()

    # 获取每个网段的 IP 统计
    segment_ips = {}
    for seg in segments:
        start_ip, end_ip = cidr_to_range(seg['network'], seg['mask'])
        seg_stats = db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='used' THEN 1 ELSE 0 END) as used,
                SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN status='gateway' THEN 1 ELSE 0 END) as gateway
            FROM ip_addresses
            WHERE pool_id=? AND ip >= ? AND ip <= ?
        """, (pid, start_ip, end_ip)).fetchone()
        segment_ips[seg['id']] = {
            'total': seg_stats['total'] if seg_stats else 0,
            'used': seg_stats['used'] if seg_stats else 0,
            'available': seg_stats['available'] if seg_stats else 0,
            'gateway': seg_stats['gateway'] if seg_stats else 0,
        }

    # 汇总统计
    all_stats = db.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='used' THEN 1 ELSE 0 END) as used,
            SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) as available,
            SUM(CASE WHEN status='gateway' THEN 1 ELSE 0 END) as gateway
        FROM ip_addresses WHERE pool_id=?
    """, (pid,)).fetchone()

    stats = type('Stats', (), {
        'used': all_stats['used'] or 0,
        'available': all_stats['available'] or 0,
        'gateway': all_stats['gateway'] or 0,
        'total': all_stats['total'] or 0,
    })()

    rooms = db.execute("SELECT id, name FROM rooms ORDER BY name").fetchall()

    return render_template("ip_pool_detail.html", pool=pool, segments=segments,
                           segment_ips=segment_ips, stats=stats, rooms=rooms)


@ip_pools_bp.route("/ip-pools/<int:pid>/segments/<int:sid>")
@login_required
def segment_detail(pid, sid):
    db = get_db()
    pool = db.execute("SELECT * FROM ip_pools WHERE id=?", (pid,)).fetchone()
    seg = db.execute("SELECT s.*, r.name as room_name FROM ip_pool_segments s LEFT JOIN rooms r ON s.room_id=r.id WHERE s.id=? AND s.pool_id=?", (sid, pid)).fetchone()
    if not pool or not seg:
        abort(404)

    start_ip, end_ip = cidr_to_range(seg['network'], seg['mask'])

    # 获取该网段的所有 IP
    ips = db.execute("""
        SELECT a.*, d.name as device_name
        FROM ip_addresses a LEFT JOIN devices d ON a.device_id=d.id
        WHERE a.pool_id=? AND a.ip >= ? AND a.ip <= ?
        ORDER BY a.ip
    """, (pid, start_ip, end_ip)).fetchall()

    # 统计
    seg_stats = db.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='used' THEN 1 ELSE 0 END) as used,
            SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) as available,
            SUM(CASE WHEN status='gateway' THEN 1 ELSE 0 END) as gateway
        FROM ip_addresses
        WHERE pool_id=? AND ip >= ? AND ip <= ?
    """, (pid, start_ip, end_ip)).fetchone()

    stats = type('Stats', (), {
        'used': seg_stats['used'] or 0,
        'available': seg_stats['available'] or 0,
        'gateway': seg_stats['gateway'] or 0,
        'total': seg_stats['total'] or 0,
    })()

    # 筛选
    status_filter = request.args.get('status', '').strip()
    if status_filter:
        ips = [a for a in ips if a['status'] == status_filter]

    return render_template("segment_detail.html", pool=pool, seg=seg, ips=ips, stats=stats, status_filter=status_filter)


@ip_pools_bp.route("/ip-pools/<int:pid>/reserve", methods=["POST"])
@write_required
def ip_reserve(pid):
    db = get_db()
    ip = request.form.get("ip", "").strip()
    device_id = request.form.get("device_id", type=int) or None
    ip_type = request.form.get("ip_type", "").strip()
    remark = request.form.get("remark", "").strip()
    if not ip:
        flash("IP 地址不能为空", "danger")
    else:
        row = db.execute("SELECT * FROM ip_addresses WHERE pool_id=? AND ip=?", (pid, ip)).fetchone()
        if not row:
            flash("IP 地址不存在", "danger")
        elif row['status'] != 'available':
            flash("该 IP 地址不可用", "danger")
        else:
            db.execute("UPDATE ip_addresses SET status='used', device_id=?, ip_type=?, remark=? WHERE id=?",
                       (device_id, ip_type, remark, row['id']))
            db.commit()
            flash(f"IP {ip} 已分配", "success")
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))


@ip_pools_bp.route("/ip-pools/<int:pid>/batch-reserve", methods=["POST"])
@write_required
def ip_batch_reserve(pid):
    db = get_db()
    ips_str = request.form.get("ips", "").strip()
    ip_type = request.form.get("ip_type", "").strip()
    remark = request.form.get("remark", "").strip()

    if not ips_str:
        flash("请选择要分配的 IP", "danger")
        return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))

    ips = [ip.strip() for ip in ips_str.split(",") if ip.strip()]
    success_count = 0
    fail_list = []

    for ip in ips:
        row = db.execute("SELECT * FROM ip_addresses WHERE pool_id=? AND ip=?", (pid, ip)).fetchone()
        if not row:
            fail_list.append(f"{ip}(不存在)")
        elif row['status'] != 'available':
            fail_list.append(f"{ip}({row['status']})")
        else:
            db.execute("UPDATE ip_addresses SET status='used', ip_type=?, remark=? WHERE id=?",
                       (ip_type, remark, row['id']))
            success_count += 1

    db.commit()
    if success_count > 0:
        flash(f"成功分配 {success_count} 个 IP", "success")
    if fail_list:
        flash(f"以下 IP 分配失败: {', '.join(fail_list[:10])}{'...' if len(fail_list) > 10 else ''}", "warning")

    # 获取 segment_id 用于回跳
    seg_id = request.form.get("sid", "")
    if seg_id:
        return redirect(url_for("ip_pools.segment_detail", pid=pid, sid=seg_id))
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))


@ip_pools_bp.route("/ip-pools/<int:pid>/batch-release", methods=["POST"])
@write_required
def ip_batch_release(pid):
    db = get_db()
    ips_str = request.form.get("ips", "").strip()

    if not ips_str:
        flash("请选择要释放的 IP", "danger")
        return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))

    ips = [ip.strip() for ip in ips_str.split(",") if ip.strip()]
    success_count = 0
    fail_list = []

    for ip in ips:
        row = db.execute("SELECT * FROM ip_addresses WHERE pool_id=? AND ip=?", (pid, ip)).fetchone()
        if not row:
            fail_list.append(f"{ip}(不存在)")
        elif row['status'] != 'used':
            fail_list.append(f"{ip}({row['status']})")
        else:
            db.execute("UPDATE ip_addresses SET status='available', device_id=NULL, ip_type='', remark='' WHERE id=?",
                       (row['id'],))
            success_count += 1

    db.commit()
    if success_count > 0:
        flash(f"成功释放 {success_count} 个 IP", "success")
    if fail_list:
        flash(f"以下 IP 释放失败: {', '.join(fail_list[:10])}{'...' if len(fail_list) > 10 else ''}", "warning")

    seg_id = request.form.get("sid", "")
    if seg_id:
        return redirect(url_for("ip_pools.segment_detail", pid=pid, sid=seg_id))
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))


@ip_pools_bp.route("/ip-pools/<int:pid>/release", methods=["POST"])
@write_required
def ip_release(pid):
    db = get_db()
    ip = request.form.get("ip", "").strip()
    if not ip:
        flash("IP 地址不能为空", "danger")
    else:
        row = db.execute("SELECT * FROM ip_addresses WHERE pool_id=? AND ip=?", (pid, ip)).fetchone()
        if not row:
            flash("IP 地址不存在", "danger")
        elif row['status'] != 'used':
            flash("该 IP 地址未被占用", "danger")
        else:
            db.execute("UPDATE ip_addresses SET status='available', device_id=NULL, ip_type='', remark='' WHERE id=?",
                       (row['id'],))
            db.commit()
            flash(f"IP {ip} 已释放", "success")
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))


@ip_pools_bp.route("/ip-pools/<int:pid>/refresh", methods=["POST"])
@write_required
def ip_pool_refresh(pid):
    db = get_db()
    sync_pool(db, pid)
    db.commit()
    flash("IP 地址池已同步刷新", "success")
    return redirect(url_for("ip_pools.ip_pool_detail", pid=pid))
