"""
CMDB Platform - 告警管理
"""
from flask import Blueprint, render_template, jsonify
from auth import login_required
from db import get_db
from config import logger
from routes.settings import load_settings

alerts_bp = Blueprint('alerts', __name__)


def get_alerts():
    """获取所有告警"""
    db = get_db()
    settings = load_settings()
    alerts = []

    # 1. 保修到期预警
    warranty_days = settings.get('warranty_alert_days', 30)
    warranty_alerts = db.execute("""
        SELECT d.id, d.name, d.warranty_date, t.name as type_name
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE d.warranty_date != '' 
        AND d.warranty_date <= date('now', '+' || ? || ' days')
        AND d.warranty_date >= date('now')
        AND s.name = '运行中'
        ORDER BY d.warranty_date
    """, (warranty_days,)).fetchall()

    for a in warranty_alerts:
        alerts.append({
            'type': 'warning',
            'category': 'warranty',
            'icon': '⏰',
            'title': f'保修即将到期',
            'message': f'{a["name"]} ({a["type_name"]}) 保修到期日期：{a["warranty_date"]}',
            'device_id': a['id'],
        })

    # 2. IP使用率告警
    ip_threshold = settings.get('ip_usage_alert_threshold', 80)
    ip_pools = db.execute("""
        SELECT p.id, p.name,
            (SELECT COUNT(*) FROM ip_addresses WHERE pool_id=p.id) as total,
            (SELECT COUNT(*) FROM ip_addresses WHERE pool_id=p.id AND status='used') as used
        FROM ip_pools p
    """).fetchall()

    for p in ip_pools:
        if p['total'] > 0:
            usage_pct = round(p['used'] / p['total'] * 100)
            if usage_pct >= ip_threshold:
                alerts.append({
                    'type': 'danger' if usage_pct >= 95 else 'warning',
                    'category': 'ip',
                    'icon': '🌐',
                    'title': f'IP地址池使用率过高',
                    'message': f'{p["name"]} 使用率 {usage_pct}% ({p["used"]}/{p["total"]})',
                    'link': f'/ip-pools/{p["id"]}',
                })

    # 3. 机柜使用率告警
    cab_threshold = settings.get('cabinet_usage_alert_threshold', 90)
    cabinets = db.execute("""
        SELECT c.id, c.name, c.u_total, r.name as room_name,
            (SELECT COUNT(*) FROM devices d WHERE d.cabinet_id=c.id AND d.u_position != '') as used
        FROM cabinets c
        LEFT JOIN rooms r ON c.room_id=r.id
    """).fetchall()

    for c in cabinets:
        if c['u_total'] > 0:
            usage_pct = round(c['used'] / c['u_total'] * 100)
            if usage_pct >= cab_threshold:
                alerts.append({
                    'type': 'danger' if usage_pct >= 100 else 'warning',
                    'category': 'cabinet',
                    'icon': '🗄️',
                    'title': f'机柜使用率过高',
                    'message': f'{c["room_name"]}/{c["name"]} 使用率 {usage_pct}% ({c["used"]}/{c["u_total"]}U)',
                    'link': f'/rooms/{c["id"]}',
                })

    # 4. 机房环境告警
    temp_high = settings.get('temperature_alert_high', 28)
    temp_low = settings.get('temperature_alert_low', 18)
    humidity_high = settings.get('humidity_alert_high', 70)
    humidity_low = settings.get('humidity_alert_low', 30)

    rooms = db.execute("SELECT id, name, temperature, humidity FROM rooms WHERE temperature IS NOT NULL OR humidity IS NOT NULL").fetchall()

    for r in rooms:
        if r['temperature'] is not None:
            if r['temperature'] > temp_high:
                alerts.append({
                    'type': 'danger',
                    'category': 'environment',
                    'icon': '🌡️',
                    'title': f'机房温度过高',
                    'message': f'{r["name"]} 温度 {r["temperature"]}°C (阈值 {temp_high}°C)',
                })
            elif r['temperature'] < temp_low:
                alerts.append({
                    'type': 'warning',
                    'category': 'environment',
                    'icon': '🌡️',
                    'title': f'机房温度过低',
                    'message': f'{r["name"]} 温度 {r["temperature"]}°C (阈值 {temp_low}°C)',
                })

        if r['humidity'] is not None:
            if r['humidity'] > humidity_high:
                alerts.append({
                    'type': 'danger',
                    'category': 'environment',
                    'icon': '💧',
                    'title': f'机房湿度过高',
                    'message': f'{r["name"]} 湿度 {r["humidity"]}% (阈值 {humidity_high}%)',
                })
            elif r['humidity'] < humidity_low:
                alerts.append({
                    'type': 'warning',
                    'category': 'environment',
                    'icon': '💧',
                    'title': f'机房湿度过低',
                    'message': f'{r["name"]} 湿度 {r["humidity"]}% (阈值 {humidity_low}%)',
                })

    # 5. 设备过保预警
    expired_alerts = db.execute("""
        SELECT d.id, d.name, d.warranty_date, t.name as type_name
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        WHERE d.warranty_date != '' 
        AND d.warranty_date < date('now')
        AND s.name = '运行中'
        LIMIT 10
    """).fetchall()

    for a in expired_alerts:
        alerts.append({
            'type': 'danger',
            'category': 'warranty_expired',
            'icon': '⚠️',
            'title': f'设备已过保',
            'message': f'{a["name"]} ({a["type_name"]}) 保修已于 {a["warranty_date"]} 到期',
            'device_id': a['id'],
        })

    return alerts


@alerts_bp.route("/alerts")
@login_required
def alert_list():
    alerts = get_alerts()
    # 按类型分组
    danger_count = len([a for a in alerts if a['type'] == 'danger'])
    warning_count = len([a for a in alerts if a['type'] == 'warning'])
    return render_template("alerts.html", alerts=alerts, danger_count=danger_count, warning_count=warning_count)


@alerts_bp.route("/api/alerts")
@login_required
def api_alerts():
    """API: 获取告警列表"""
    alerts = get_alerts()
    return jsonify({
        'total': len(alerts),
        'danger': len([a for a in alerts if a['type'] == 'danger']),
        'warning': len([a for a in alerts if a['type'] == 'warning']),
        'alerts': alerts[:20]
    })
