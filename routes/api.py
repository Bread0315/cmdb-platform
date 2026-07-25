"""
CMDB Platform - API 接口
统计、导入导出、批量操作
"""
import io
import csv
from flask import Blueprint, request, session, jsonify, send_file, abort, render_template
from auth import login_required, write_required
from db import get_db, log_to_db
from config import logger

api_bp = Blueprint('api', __name__)


@api_bp.route("/api/stats")
@login_required
def api_stats():
    db = get_db()
    type_stats = db.execute("""
        SELECT t.name, COUNT(d.id) as cnt
        FROM device_types t LEFT JOIN devices d ON d.device_type_id=t.id
        GROUP BY t.id ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    state_stats = db.execute("""
        SELECT s.name, s.id, COUNT(d.id) as cnt
        FROM lifecycle_states s LEFT JOIN devices d ON d.lifecycle_state_id=s.id
        GROUP BY s.id ORDER BY s.sort
    """).fetchall()
    return jsonify({
        "type_stats": [dict(r) for r in type_stats],
        "state_stats": [dict(r) for r in state_stats],
    })


@api_bp.route("/api/devices/export")
@login_required
def api_devices_export():
    db = get_db()
    devices = db.execute("""
        SELECT d.name, t.name as type_name, d.brand, d.model, d.asset_code, d.serial_number,
               d.biz_ip, d.oob_ip, d.mac_address, d.u_position, d.u_height,
               d.location, d.department, d.custodian, d.user_name, d.rack_date, d.warranty_date,
               d.purchase_price, s.name as state_name, d.remark, d.tag,
               c.name as cabinet_name, r.name as room_name
        FROM devices d
        JOIN device_types t ON d.device_type_id=t.id
        JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
        LEFT JOIN cabinets c ON d.cabinet_id=c.id
        LEFT JOIN rooms r ON c.room_id=r.id
        ORDER BY d.id
    """).fetchall()

    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel
    writer = csv.writer(output)
    writer.writerow(['设备名称', '类型', '品牌', '型号', '资产编号', 'SN码', '业务IP', '带外IP', 'MAC地址',
                     'U位', 'U高', '位置', '部门', '负责人', '领用人', '上架时间', '保修到期',
                     '采购价格', '状态', '备注', '标签', '机柜', '机房'])
    for d in devices:
        writer.writerow([
            d['name'], d['type_name'], d['brand'], d['model'], d['asset_code'], d['serial_number'],
            d['biz_ip'], d['oob_ip'], d['mac_address'], d['u_position'], d['u_height'],
            d['location'], d['department'], d['custodian'], d['user_name'], d['rack_date'], d['warranty_date'],
            d['purchase_price'], d['state_name'], d['remark'], d['tag'],
            d['cabinet_name'], d['room_name']
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='devices_export.csv'
    )


@api_bp.route("/api/devices/batch-delete", methods=["POST"])
@write_required
def api_batch_delete():
    db = get_db()
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or request.form.getlist("ids")
    if not ids:
        return jsonify({"ok": False, "error": "未选择设备"}), 400
    ids = [int(i) for i in ids]
    placeholders = ','.join('?' * len(ids))
    db.execute(f"DELETE FROM devices WHERE id IN ({placeholders})", ids)
    log_to_db(db, 'WARNING', '资产管理', '批量删除', f"批量删除 {len(ids)} 台设备")
    db.commit()
    logger.warning(f"批量删除 {len(ids)} 台设备 by {session.get('username')}")
    return jsonify({"ok": True, "count": len(ids)})


@api_bp.route("/api/devices/template")
@login_required
def api_devices_template():
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['设备名称', '类型', '品牌', '型号', '资产编号', 'SN码', '业务IP', '带外IP', 'MAC地址',
                     'U位', 'U高(1/2/4)', '位置', '部门', '负责人', '领用人', '采购日期', '保修到期',
                     '采购价格', '生命周期状态', '备注', '标签'])
    writer.writerow(['Web服务器-01', '服务器', 'Dell', 'R740', 'IT-2025-001', 'SN20260001',
                     '192.168.1.100', '10.0.0.100', 'AA:BB:CC:DD:EE:FF',
                     'U1-U2', '2', 'A栋3楼', '技术部', '张三', '', '2026-01-01', '2029-01-01',
                     '50000', '运行中', '生产环境', '生产,核心'])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='devices_template.csv'
    )


@api_bp.route("/api/devices/import", methods=["GET", "POST"])
@login_required
def api_devices_import():
    db = get_db()
    if request.method == "GET":
        types = db.execute("SELECT * FROM device_types ORDER BY name").fetchall()
        states = db.execute("SELECT * FROM lifecycle_states ORDER BY sort").fetchall()
        return render_template("device_import.html", types=types, states=states)

    file = request.files.get("file")
    if not file:
        flash("请上传 CSV 文件", "danger")
        return '', 400

    try:
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
    except Exception as e:
        flash(f"文件解析失败: {e}", "danger")
        return '', 400

    types_map = {r['name']: r['id'] for r in db.execute("SELECT id, name FROM device_types").fetchall()}
    state_map = {r['name']: r['id'] for r in db.execute("SELECT id, name FROM lifecycle_states").fetchall()}

    success_count = 0
    error_rows = []

    for i, row in enumerate(rows, 2):
        name = row.get('设备名称', '').strip()
        type_name = row.get('类型', '').strip()
        state_name = row.get('生命周期状态', '').strip()

        if not name:
            error_rows.append(f"第{i}行: 设备名称为空")
            continue
        if type_name not in types_map:
            error_rows.append(f"第{i}行: 类型 '{type_name}' 不存在")
            continue
        if state_name not in state_map:
            error_rows.append(f"第{i}行: 状态 '{state_name}' 不存在")
            continue

        try:
            db.execute("""
                INSERT INTO devices(name, device_type_id, brand, model, asset_code, serial_number,
                    biz_ip, oob_ip, mac_address, u_position, u_height, location, department,
                    custodian, user_name, rack_date, warranty_date, purchase_price,
                    lifecycle_state_id, remark, tag, created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                name, types_map[type_name],
                row.get('品牌', '').strip(), row.get('型号', '').strip(),
                row.get('资产编号', '').strip(), row.get('SN码', '').strip(),
                row.get('业务IP', '').strip(), row.get('带外IP', '').strip(),
                row.get('MAC地址', '').strip(),
                row.get('U位', '').strip(), int(row.get('U高(1/2/4)', 1) or 1),
                row.get('位置', '').strip(), row.get('部门', '').strip(),
                row.get('负责人', '').strip(), row.get('领用人', '').strip(),
                row.get('上架时间', '').strip(),
                row.get('保修到期', '').strip(), float(row.get('采购价格', 0) or 0),
                state_map[state_name], row.get('备注', '').strip(),
                row.get('标签', '').strip(), session['user_id']
            ))
            success_count += 1
        except Exception as e:
            error_rows.append(f"第{i}行: {e}")

    log_to_db(db, 'INFO', '资产管理', '批量导入', f"导入成功 {success_count} 台，失败 {len(error_rows)} 台")
    db.commit()

    if error_rows:
        flash(f"导入完成: 成功 {success_count} 台，失败 {len(error_rows)} 台", "warning")
    else:
        flash(f"导入成功: 共 {success_count} 台设备", "success")
    logger.info(f"批量导入设备: 成功{success_count} 失败{len(error_rows)} by {session.get('username')}")

    if error_rows:
        return jsonify({"ok": True, "success": success_count, "errors": error_rows})
    return jsonify({"ok": True, "success": success_count})
