"""
CMDB Platform - 拓扑视图
"""
from flask import Blueprint, render_template
from auth import login_required
from db import get_db

topology_bp = Blueprint('topology', __name__)


@topology_bp.route("/topology")
@login_required
def topology():
    db = get_db()
    systems = db.execute("""
        SELECT bs.id, bs.name, bs.status, bs.department,
            (SELECT COUNT(*) FROM system_device_rel WHERE system_id=bs.id) as device_count
        FROM business_systems bs ORDER BY bs.name
    """).fetchall()

    nodes = []
    links = []
    node_ids = set()

    for sys in systems:
        nodes.append({"id": f"sys_{sys['id']}", "name": sys['name'], "type": "system", "status": sys['status']})
        rels = db.execute("""
            SELECT d.id, d.name, s.name as state_name
            FROM system_device_rel sdr
            JOIN devices d ON sdr.device_id=d.id
            JOIN lifecycle_states s ON d.lifecycle_state_id=s.id
            WHERE sdr.system_id=? AND s.name NOT IN ('已下架', '已报废')
        """, (sys['id'],)).fetchall()
        for r in rels:
            if r['id'] not in node_ids:
                nodes.append({"id": f"dev_{r['id']}", "name": r['name'], "type": "device", "status": r['state_name']})
                node_ids.add(r['id'])
            links.append({"source": f"sys_{sys['id']}", "target": f"dev_{r['id']}"})

    return render_template("topology.html", systems=systems, nodes=nodes, links=links)
