"""
CMDB Platform - 仪表盘
"""
from flask import Blueprint, render_template, session
from auth import login_required
from db import get_db

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route("/")
@login_required
def dashboard():
    db = get_db()

    # 基础统计
    stats = {}
    row = db.execute("""
        SELECT
            (SELECT COUNT(*) FROM devices) as total_devices,
            (SELECT COUNT(*) FROM device_types) as total_types,
            (SELECT COUNT(*) FROM users) as total_users,
            (SELECT COUNT(*) FROM rooms) as total_rooms,
            (SELECT COUNT(*) FROM cabinets) as total_cabinets,
            (SELECT COUNT(*) FROM business_systems) as total_systems
    """).fetchone()
    stats.update({k: row[k] for k in row.keys()})

    stats["online_devices"] = db.execute(
        "SELECT COUNT(*) FROM devices d JOIN lifecycle_states s ON d.lifecycle_state_id=s.id WHERE s.name='运行中'"
    ).fetchone()[0]

    stats["warranty_alert"] = db.execute(
        "SELECT COUNT(*) FROM devices WHERE warranty_date != '' AND warranty_date <= date('now', '+30 days') AND warranty_date >= date('now')"
    ).fetchone()[0]

    stats["idle_devices"] = db.execute(
        "SELECT COUNT(*) FROM devices d JOIN lifecycle_states s ON d.lifecycle_state_id=s.id WHERE s.name IN ('已下架','已报废')"
    ).fetchone()[0]

    # 按机房统计：IP使用率、资产价值、机柜使用率
    rooms_list = db.execute("SELECT id, name FROM rooms ORDER BY name").fetchall()
    room_stats = []
    for r in rooms_list:
        rid = r['id']
        rname = r['name']

        # IP使用率：该机房网段下的IP使用情况
        ip_info = db.execute("""
            SELECT
                COUNT(a.id) as total,
                SUM(CASE WHEN a.status='used' THEN 1 ELSE 0 END) as used
            FROM ip_pool_segments s
            JOIN ip_addresses a ON a.pool_id = s.pool_id
            WHERE s.room_id = ?
        """, (rid,)).fetchone()
        ip_total = ip_info['total'] if ip_info else 0
        ip_used = ip_info['used'] if ip_info else 0

        # 机柜使用率：已用U位 / 总U位
        cab_total_u = db.execute("SELECT COALESCE(SUM(u_total), 0) FROM cabinets WHERE room_id=?", (rid,)).fetchone()[0]
        cab_used_u = db.execute("""
            SELECT COALESCE(SUM(d.u_height), 0)
            FROM devices d
            WHERE d.room_id = ? OR d.cabinet_id IN (SELECT id FROM cabinets WHERE room_id = ?)
        """, (rid, rid)).fetchone()[0]

        room_stats.append({
            'name': rname,
            'ip_used': ip_used,
            'ip_total': ip_total,
            'ip_pct': round(ip_used / ip_total * 100, 1) if ip_total > 0 else 0,
            'cab_used': cab_used_u,
            'cab_total': cab_total_u,
            'cab_pct': round(cab_used_u / cab_total_u * 100, 1) if cab_total_u > 0 else 0,
        })
    stats["room_stats"] = room_stats

    # 分类统计
    category_stats = db.execute("""
        SELECT t.category, COUNT(d.id) as cnt
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        GROUP BY t.category
    """).fetchall()
    stats["cat_stats"] = {r['category']: r['cnt'] for r in category_stats}
    stats["cat_hardware"] = stats["cat_stats"].get("hardware", 0)
    stats["cat_network"] = stats["cat_stats"].get("network", 0)
    stats["cat_infrastructure"] = stats["cat_stats"].get("infrastructure", 0)
    stats["cat_software"] = stats["cat_stats"].get("software", 0)
    stats["cat_office"] = stats["cat_stats"].get("office", 0)
    stats["cat_other"] = stats["cat_stats"].get("other", 0)

    # 资产总值
    stats["total_value"] = db.execute(
        "SELECT COALESCE(SUM(purchase_price), 0) FROM devices"
    ).fetchone()[0]

    # 运行中资产价值
    stats["active_value"] = db.execute("""
        SELECT COALESCE(SUM(d.purchase_price), 0)
        FROM devices d
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE s.name='运行中'
    """).fetchone()[0]

    # 已下架/报废资产价值
    stats["idle_value"] = db.execute("""
        SELECT COALESCE(SUM(d.purchase_price), 0)
        FROM devices d
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE s.name IN ('已下架','已报废')
    """).fetchone()[0]

    # 分类资产价值（按状态）
    value_stats = db.execute("""
        SELECT
            CASE t.category
                WHEN 'hardware' THEN '硬件资产'
                WHEN 'network' THEN '网络设备'
                WHEN 'infrastructure' THEN '机房基础设施'
                WHEN 'software' THEN '软件资产'
                WHEN 'office' THEN '办公资产'
                ELSE '其他配件'
            END as name,
            COALESCE(SUM(CASE WHEN s.name='运行中' THEN d.purchase_price ELSE 0 END), 0) as active_value,
            COALESCE(SUM(CASE WHEN s.name IN ('已下架','已报废') THEN d.purchase_price ELSE 0 END), 0) as idle_value
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        GROUP BY t.category
        HAVING active_value > 0 OR idle_value > 0
        ORDER BY (active_value + idle_value) DESC
    """).fetchall()
    stats["value_stats"] = [dict(r) for r in value_stats]

    # 按机房+分类的价值统计（运行中/已下架分开）
    room_value_stats = db.execute("""
        SELECT
            COALESCE(r1.name, r2.name) as room_name,
            CASE t.category
                WHEN 'hardware' THEN '服务器'
                WHEN 'network' THEN '网络设备'
                WHEN 'infrastructure' THEN '基础设施'
                WHEN 'software' THEN '软件'
                WHEN 'office' THEN '办公资产'
                ELSE '其他'
            END as cat_name,
            COALESCE(SUM(CASE WHEN s.name='运行中' THEN d.purchase_price ELSE 0 END), 0) as running_value,
            COALESCE(SUM(CASE WHEN s.name IN ('已下架','已报废') THEN d.purchase_price ELSE 0 END), 0) as idle_value
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        LEFT JOIN cabinets c ON d.cabinet_id=c.id
        LEFT JOIN rooms r1 ON c.room_id=r1.id
        LEFT JOIN rooms r2 ON d.room_id=r2.id
        GROUP BY room_name, cat_name
        HAVING running_value > 0 OR idle_value > 0
        ORDER BY room_name, (running_value + idle_value) DESC
    """).fetchall()
    # 按机房分组
    room_values = {}
    for rv in room_value_stats:
        rn = rv['room_name'] or '未分配'
        if rn not in room_values:
            room_values[rn] = {'categories': [], 'total': 0}
        room_values[rn]['categories'].append({
            'cat': rv['cat_name'],
            'running': rv['running_value'],
            'idle': rv['idle_value'],
            'total': rv['running_value'] + rv['idle_value'],
        })
        room_values[rn]['total'] += rv['running_value'] + rv['idle_value']
    stats["room_values"] = room_values

    # 类型分布（取前10）
    type_stats = db.execute("""
        SELECT t.name, COUNT(d.id) as cnt
        FROM device_types t LEFT JOIN devices d ON d.device_type_id=t.id
        GROUP BY t.id ORDER BY cnt DESC LIMIT 10
    """).fetchall()

    # 状态分布
    state_stats = db.execute("""
        SELECT s.name, s.id, COUNT(d.id) as cnt
        FROM lifecycle_states s LEFT JOIN devices d ON d.lifecycle_state_id=s.id
        GROUP BY s.id ORDER BY s.sort
    """).fetchall()

    # 分类分布（图表用）
    cat_chart_stats = db.execute("""
        SELECT
            CASE t.category
                WHEN 'hardware' THEN '硬件资产'
                WHEN 'network' THEN '网络设备'
                WHEN 'infrastructure' THEN '机房基础设施'
                WHEN 'software' THEN '软件资产'
                WHEN 'office' THEN '办公资产'
                ELSE '其他配件'
            END as name,
            COUNT(d.id) as cnt
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        GROUP BY t.category
        ORDER BY cnt DESC
    """).fetchall()

    # 最近操作
    recent_logs = db.execute("""
        SELECT l.*, u.username FROM device_logs l
        LEFT JOIN users u ON l.user_id=u.id
        ORDER BY l.created_at DESC LIMIT 10
    """).fetchall()

    # IP地址池统计
    ip_pool_stats = db.execute("""
        SELECT
            p.id,
            p.name,
            (SELECT COUNT(*) FROM ip_pool_segments WHERE pool_id=p.id) as segment_count,
            COUNT(a.id) as total_ips,
            SUM(CASE WHEN a.status='used' THEN 1 ELSE 0 END) as used_ips,
            SUM(CASE WHEN a.status='available' THEN 1 ELSE 0 END) as available_ips
        FROM ip_pools p
        LEFT JOIN ip_addresses a ON a.pool_id=p.id
        GROUP BY p.id
        ORDER BY p.name
    """).fetchall()
    stats["ip_pools"] = [dict(r) for r in ip_pool_stats]
    stats["total_ip_pools"] = len(ip_pool_stats)
    stats["total_ips"] = db.execute("SELECT COUNT(*) FROM ip_addresses").fetchone()[0]
    stats["used_ips"] = db.execute("SELECT COUNT(*) FROM ip_addresses WHERE status='used'").fetchone()[0]

    # 每个池的网段信息
    pool_segments_map = {}
    all_segs = db.execute("""
        SELECT s.pool_id, s.network, s.mask, s.gateway, s.vlan, r.name as room_name, r.id as room_id
        FROM ip_pool_segments s
        LEFT JOIN rooms r ON s.room_id = r.id
        ORDER BY s.pool_id, s.network
    """).fetchall()
    for s in all_segs:
        pid = s['pool_id']
        if pid not in pool_segments_map:
            pool_segments_map[pid] = []
        pool_segments_map[pid].append(dict(s))
    stats["pool_segments"] = pool_segments_map

    # 按机房分组的地址池数据
    ip_pools_map = {p['id']: dict(p) for p in ip_pool_stats}
    pools_by_room = {}
    for seg in all_segs:
        room_name = seg['room_name'] or '未分配'
        pid = seg['pool_id']
        if room_name not in pools_by_room:
            pools_by_room[room_name] = {}
        if pid not in pools_by_room[room_name]:
            pools_by_room[room_name][pid] = ip_pools_map.get(pid, {})
    stats["pools_by_room"] = pools_by_room

    # 资产趋势数据（按月统计）
    trend_data = db.execute("""
        SELECT
            strftime('%Y-%m', rack_date) as month,
            COUNT(*) as total,
            SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name='运行中') THEN 1 ELSE 0 END) as running,
            SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name='已下架') THEN 1 ELSE 0 END) as offline,
            SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name='已报废') THEN 1 ELSE 0 END) as scrapped,
            COALESCE(SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name='运行中') THEN purchase_price ELSE 0 END), 0) as running_value,
            COALESCE(SUM(CASE WHEN lifecycle_state_id IN (SELECT id FROM lifecycle_states WHERE name IN ('已下架','已报废')) THEN purchase_price ELSE 0 END), 0) as idle_value
        FROM devices
        WHERE rack_date >= date('now', '-12 months') AND rack_date != ''
        GROUP BY strftime('%Y-%m', rack_date)
        ORDER BY month
    """).fetchall()
    stats["trend_data"] = [dict(r) for r in trend_data]

    # 最近新增资产
    recent_devices = db.execute("""
        SELECT d.id, d.name, t.name as type_name,
               CASE t.category
                   WHEN 'hardware' THEN '硬件'
                   WHEN 'network' THEN '网络'
                   WHEN 'infrastructure' THEN '基础设施'
                   WHEN 'software' THEN '软件'
                   WHEN 'office' THEN '办公'
                   ELSE '其他'
               END as cat_name,
               d.created_at
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        ORDER BY d.created_at DESC LIMIT 8
    """).fetchall()

    online_state = db.execute("SELECT id FROM lifecycle_states WHERE name='运行中' ORDER BY sort").fetchone()
    online_state_id = online_state['id'] if online_state else ''
    idle_states = db.execute("SELECT id FROM lifecycle_states WHERE name IN ('已下架', '已报废') ORDER BY sort").fetchall()
    idle_state_ids = ','.join(str(s['id']) for s in idle_states) if idle_states else ''

    return render_template("dashboard.html", stats=stats, type_stats=type_stats,
                           state_stats=state_stats, cat_chart_stats=cat_chart_stats,
                           recent_logs=recent_logs, recent_devices=recent_devices,
                           online_state_id=online_state_id, idle_state_ids=idle_state_ids)
