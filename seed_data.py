"""
CMDB Platform - 测试数据生成脚本
清理现有演示数据，按指定要求生成新数据
"""
import sqlite3
import random
import string
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = "cmdb.db"


def random_mac():
    return ":".join("".join(random.choices("0123456789ABCDEF", k=2)) for _ in range(6))


def random_serial(prefix, idx):
    return f"{prefix}-{idx:04d}"


def random_date(start_year=2020, end_year=2025):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = (end - start).days
    d = start + timedelta(days=random.randint(0, delta))
    return d.strftime("%Y-%m-%d")


def seed():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")
    cur = db.cursor()

    print("1. 清理现有演示数据...")
    # 按依赖顺序删除
    db.execute("DELETE FROM ci_relationships")
    db.execute("DELETE FROM system_device_rel")
    db.execute("DELETE FROM device_logs")
    db.execute("DELETE FROM system_logs")
    db.execute("DELETE FROM ip_addresses")
    db.execute("DELETE FROM ip_pool_segments")
    db.execute("DELETE FROM ip_pools")
    db.execute("DELETE FROM devices")
    db.execute("DELETE FROM cabinets")
    db.execute("DELETE FROM rooms")
    db.execute("DELETE FROM business_systems")
    db.execute("DELETE FROM login_logs")
    db.commit()

    # 保留 users, device_types, lifecycle_states
    print("   保留 users, device_types, lifecycle_states 表")

    # 获取类型 ID
    rack_server_id = cur.execute("SELECT id FROM device_types WHERE name='机架服务器'").fetchone()[0]
    switch_id = cur.execute("SELECT id FROM device_types WHERE name='交换机'").fetchone()[0]
    firewall_id = cur.execute("SELECT id FROM device_types WHERE name='防火墙'").fetchone()[0]
    storage_id = cur.execute("SELECT id FROM device_types WHERE name='存储设备'").fetchone()[0]
    os_id = cur.execute("SELECT id FROM device_types WHERE name='操作系统'").fetchone()[0]
    db_type_id = cur.execute("SELECT id FROM device_types WHERE name='数据库'").fetchone()[0]
    middleware_id = cur.execute("SELECT id FROM device_types WHERE name='中间件'").fetchone()[0]
    virtual_id = cur.execute("SELECT id FROM device_types WHERE name='虚拟化平台'").fetchone()[0]
    container_id = cur.execute("SELECT id FROM device_types WHERE name='容器平台'").fetchone()[0]
    monitor_sw_id = cur.execute("SELECT id FROM device_types WHERE name='监控软件'").fetchone()[0]
    security_sw_id = cur.execute("SELECT id FROM device_types WHERE name='安全软件'").fetchone()[0]
    backup_sw_id = cur.execute("SELECT id FROM device_types WHERE name='备份软件'").fetchone()[0]
    desktop_id = cur.execute("SELECT id FROM device_types WHERE name='台式机'").fetchone()[0]
    laptop_id = cur.execute("SELECT id FROM device_types WHERE name='笔记本'").fetchone()[0]
    printer_id = cur.execute("SELECT id FROM device_types WHERE name='打印机'").fetchone()[0]

    running_id = cur.execute("SELECT id FROM lifecycle_states WHERE name='运行中'").fetchone()[0]
    offline_id = cur.execute("SELECT id FROM lifecycle_states WHERE name='已下架'").fetchone()[0]
    scrapped_id = cur.execute("SELECT id FROM lifecycle_states WHERE name='已报废'").fetchone()[0]

    print("2. 创建机房...")
    rooms_data = [
        ("陆家嘴管理机房", "上海", "浦东新区", "杨高南路759号"),
        ("金桥核心交易机房", "上海", "浦东新区", "龙沪路399号"),
        ("宁桥路同城机房", "上海", "浦东新区", "宁桥路801号"),
        ("天津灾备机房", "天津", "西青区", "花苑产业园"),
    ]
    room_ids = {}
    for name, city, district, addr in rooms_data:
        cur.execute("INSERT INTO rooms(name, building, floor, location, remark) VALUES(?,?,?,?,?)",
                   (name, city, district, addr, f"{city}{district}{addr}"))
        room_ids[name] = cur.lastrowid
    db.commit()

    print("3. 创建机柜（每个机房10个）...")
    cabinet_ids = {}
    for room_name, rid in room_ids.items():
        cabinet_ids[room_name] = []
        for i in range(1, 11):
            cur.execute("INSERT INTO cabinets(room_id, name, u_total, power, remark) VALUES(?,?,?,?,?)",
                       (rid, f"C{i:02d}", 42, "双路 220V 32A", f"{room_name} C{i:02d}"))
            cabinet_ids[room_name].append(cur.lastrowid)
    db.commit()

    print("4. 创建IP地址池...")
    # 带外地址池
    oob_pool_id = cur.execute("INSERT INTO ip_pools(name, remark, created_by) VALUES(?,?,1)",
                              ("带外管理地址池", "设备带外管理网段")).lastrowid
    # 业务地址池
    biz_pool_id = cur.execute("INSERT INTO ip_pools(name, remark, created_by) VALUES(?,?,1)",
                              ("业务地址池", "业务系统及服务器网段")).lastrowid
    db.commit()

    # 带外网段
    oob_segments = [
        ("10.10.9.0", 24, "10.10.9.254", "VLAN901", room_ids["陆家嘴管理机房"]),
        ("10.11.9.0", 24, "10.11.9.254", "VLAN902", room_ids["宁桥路同城机房"]),
        ("10.12.9.0", 24, "10.12.9.254", "VLAN903", room_ids["天津灾备机房"]),
        ("10.16.66.0", 24, "10.16.66.254", "VLAN904", room_ids["金桥核心交易机房"]),
    ]
    for network, mask, gw, vlan, rid in oob_segments:
        cur.execute("INSERT INTO ip_pool_segments(pool_id, network, mask, gateway, vlan, room_id, remark) VALUES(?,?,?,?,?,?,?)",
                   (oob_pool_id, network, mask, gw, vlan, rid, f"带外管理-{network}/{mask}"))
    db.commit()

    # 业务网段
    biz_segments = [
        ("10.10.10.0", 24, "10.10.10.254", "VLAN101", room_ids["陆家嘴管理机房"]),
        ("10.168.10.0", 24, "10.168.10.254", "VLAN102", room_ids["陆家嘴管理机房"]),
        ("10.11.11.0", 24, "10.11.11.254", "VLAN111", room_ids["宁桥路同城机房"]),
        ("10.169.10.0", 24, "10.169.10.254", "VLAN112", room_ids["宁桥路同城机房"]),
        ("10.12.10.0", 24, "10.12.10.254", "VLAN121", room_ids["天津灾备机房"]),
        ("10.170.10.0", 24, "10.170.10.254", "VLAN122", room_ids["天津灾备机房"]),
        ("10.16.70.0", 24, "10.16.70.254", "VLAN131", room_ids["金桥核心交易机房"]),
        ("10.16.110.0", 24, "10.16.110.254", "VLAN132", room_ids["金桥核心交易机房"]),
    ]
    for network, mask, gw, vlan, rid in biz_segments:
        cur.execute("INSERT INTO ip_pool_segments(pool_id, network, mask, gateway, vlan, room_id, remark) VALUES(?,?,?,?,?,?,?)",
                   (biz_pool_id, network, mask, gw, vlan, rid, f"业务地址-{network}/{mask}"))
    db.commit()

    print("5. 同步IP地址...")
    from routes.ip_pools import sync_all_ip_pools
    sync_all_ip_pools(db)
    db.commit()

    print("6. 创建设备（每机房服务器50+交换机50+防火墙50）...")
    departments = ["技术部", "运维部", "数据库组", "网络组", "安全组", "开发部"]
    custodians = ["张三", "李四", "王五", "赵六", "孙七", "周八", "吴九", "钱十"]

    device_count = 0
    for room_name, rid in room_ids.items():
        cabs = cabinet_ids[room_name]
        # 根据机房确定业务网段前缀
        if room_name == "陆家嘴管理机房":
            biz_prefix = "10.10.10"
            oob_prefix = "10.10.9"
        elif room_name == "金桥核心交易机房":
            biz_prefix = "10.16.70"
            oob_prefix = "10.16.66"
        elif room_name == "宁桥路同城机房":
            biz_prefix = "10.11.11"
            oob_prefix = "10.11.9"
        else:  # 天津灾备机房
            biz_prefix = "10.12.10"
            oob_prefix = "10.12.9"

        # 服务器 50 台（每机柜5台，2U高度，从U42向下排列）
        for i in range(1, 51):
            cab_idx = (i - 1) % 10  # 0-9 对应10个机柜
            cab_id = cabs[cab_idx]
            server_in_cab = (i - 1) // 10  # 0-4 每机柜5台
            u_pos = f"U{42 - server_in_cab * 2}"  # U42, U40, U38, U36, U34
            u_height = 2
            state = running_id if random.random() > 0.1 else offline_id
            dept = random.choice(departments)
            custodian = random.choice(custodians)
            brand = random.choice(["Dell", "HP", "Lenovo", "Inspur"])
            model = random.choice(["R750", "R740", "DL380", "SR650", "NF5280"])
            biz_ip = f"{biz_prefix}.{i + 10}"
            oob_ip = f"{oob_prefix}.{i + 10}"
            price = random.randint(50000, 150000)

            cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
                lifecycle_state_id, department, custodian, rack_date, warranty_date,
                purchase_price, tag, created_by, room_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (f"SRV-{room_name[:2]}-{i:03d}", rack_server_id, brand, model,
                 random_serial("SRV", device_count + i), biz_ip, oob_ip, random_mac(),
                 cab_id, u_pos, u_height, state, dept, custodian,
                 random_date(2022, 2024), random_date(2025, 2028),
                 price, "服务器", rid))
        device_count += 50

        # 交换机 50 台（每机柜5台，1U高度，从U1向上排列）
        for i in range(1, 51):
            cab_idx = (i - 1) % 10
            cab_id = cabs[cab_idx]
            sw_in_cab = (i - 1) // 10  # 0-4 每机柜5台
            u_pos = f"U{sw_in_cab + 1}"  # U1, U2, U3, U4, U5
            u_height = 1
            state = running_id
            dept = "网络组"
            brand = random.choice(["Cisco", "H3C", "Huawei", "Ruijie"])
            model = random.choice(["C9300", "C9200", "S5130", "CE6800", "S5735"])
            biz_ip = f"{biz_prefix}.{i + 200}"
            oob_ip = f"{oob_prefix}.{i + 200}"
            price = random.randint(8000, 50000)

            cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
                lifecycle_state_id, department, custodian, rack_date, warranty_date,
                purchase_price, tag, created_by, room_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (f"SW-{room_name[:2]}-{i:03d}", switch_id, brand, model,
                 random_serial("SW", device_count + i), biz_ip, oob_ip, random_mac(),
                 cab_id, u_pos, u_height, state, dept, random.choice(custodians),
                 random_date(2022, 2024), random_date(2025, 2028),
                 price, "交换机,网络", rid))
        device_count += 50

        # 防火墙 50 台（每机柜5台，1U高度，从U6向上排列）
        for i in range(1, 51):
            cab_idx = (i - 1) % 10
            cab_id = cabs[cab_idx]
            fw_in_cab = (i - 1) // 10  # 0-4 每机柜5台
            u_pos = f"U{fw_in_cab + 6}"  # U6, U7, U8, U9, U10
            u_height = 1
            state = running_id
            dept = "安全组"
            brand = random.choice(["Fortinet", "PaloAlto", "CheckPoint", "H3C"])
            model = random.choice(["FG-200F", "PA-220", "R80.10", "F5060"])
            biz_ip = f"{biz_prefix}.{i + 100}"
            oob_ip = f"{oob_prefix}.{i + 100}"
            price = random.randint(15000, 80000)

            cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
                lifecycle_state_id, department, custodian, rack_date, warranty_date,
                purchase_price, tag, created_by, room_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (f"FW-{room_name[:2]}-{i:03d}", firewall_id, brand, model,
                 random_serial("FW", device_count + i), biz_ip, oob_ip, random_mac(),
                 cab_id, u_pos, u_height, state, dept, random.choice(custodians),
                 random_date(2022, 2024), random_date(2025, 2028),
                 price, "防火墙,安全", rid))
        device_count += 50

    db.commit()

    print("7. 关联设备IP到地址池...")
    # 获取所有IP地址池网段信息
    all_segments = db.execute("""
        SELECT s.id, s.pool_id, s.network, s.mask, s.room_id
        FROM ip_pool_segments s
    """).fetchall()

    for seg in all_segments:
        seg_id, pool_id, network, mask, room_id = seg
        # 获取该网段下的所有IP
        ips = db.execute("SELECT id, ip FROM ip_addresses WHERE pool_id=?", (pool_id,)).fetchall()
        ip_map = {row[1]: row[0] for row in ips}

        # 获取该机房的设备
        if network.startswith("10.10.9") or network.startswith("10.11.9") or \
           network.startswith("10.12.9") or network.startswith("10.16.66"):
            # 带外网段，匹配 oob_ip
            devices = db.execute("SELECT id, oob_ip FROM devices WHERE room_id=? AND oob_ip != '-'", (room_id,)).fetchall()
        else:
            # 业务网段，匹配 biz_ip
            devices = db.execute("SELECT id, biz_ip FROM devices WHERE room_id=? AND biz_ip != '-'", (room_id,)).fetchall()

        for d in devices:
            dev_id, dev_ip = d
            if dev_ip in ip_map:
                db.execute("UPDATE ip_addresses SET status='used', device_id=? WHERE id=?", (dev_id, ip_map[dev_ip]))

    db.commit()

    print("8. 创建软件资产...")
    sw_ids = []
    sw_items = [
        ("CentOS 7.9", os_id, "Red Hat", "CentOS 7.9", "操作系统", 200),
        ("CentOS 8.5", os_id, "Red Hat", "CentOS 8.5", "操作系统", 150),
        ("Ubuntu 22.04 LTS", os_id, "Canonical", "Ubuntu 22.04", "操作系统", 80),
        ("Windows Server 2022", os_id, "Microsoft", "Windows Server 2022", "操作系统", 60),
        ("MySQL 8.0", db_type_id, "Oracle", "MySQL 8.0.35", "数据库", 300),
        ("PostgreSQL 14", db_type_id, "PostgreSQL", "PostgreSQL 14.10", "数据库", 120),
        ("Redis 7.2", db_type_id, "Redis", "Redis 7.2.4", "数据库", 200),
        ("Oracle 19c", db_type_id, "Oracle", "Oracle 19c", "数据库", 40),
        ("Nginx 1.24", middleware_id, "Nginx", "Nginx 1.24.0", "中间件", 250),
        ("Tomcat 9.0", middleware_id, "Apache", "Tomcat 9.0.82", "中间件", 180),
        ("Kafka 3.6", middleware_id, "Apache", "Kafka 3.6", "中间件", 100),
        ("VMware vSphere 8", virtual_id, "VMware", "vSphere 8.0", "虚拟化", 50),
        ("Proxmox VE 8", virtual_id, "Proxmox", "VE 8.0", "虚拟化", 30),
        ("Docker CE 24.0", container_id, "Docker", "Docker CE 24.0", "容器", 400),
        ("Kubernetes 1.28", container_id, "CNCF", "Kubernetes 1.28", "容器", 150),
        ("Zabbix 6.4", monitor_sw_id, "Zabbix", "Zabbix 6.4 LTS", "监控", 80),
        ("Grafana 10.2", monitor_sw_id, "Grafana", "Grafana 10.2", "监控", 60),
        ("Prometheus 2.48", monitor_sw_id, "Prometheus", "Prometheus 2.48", "监控", 70),
        ("FortiClient 7.2", security_sw_id, "Fortinet", "FortiClient 7.2", "安全", 100),
        ("Splunk 9.1", security_sw_id, "Splunk", "Splunk 9.1", "安全", 25),
        ("Veeam Backup 12", backup_sw_id, "Veeam", "Veeam Backup 12", "备份", 40),
        ("Veritas NetBackup 10", backup_sw_id, "Veritas", "NetBackup 10", "备份", 20),
    ]

    for sw_name, type_id, brand, model, tag, qty in sw_items:
        cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
            biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
            lifecycle_state_id, department, custodian, purchase_date, warranty_date,
            purchase_price, tag, created_by, quantity, license_key)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (sw_name, type_id, brand, model,
             f"SW-{len(sw_ids)+1:04d}", "-", "-", "-",
             None, "-", 1, running_id, "运维部", "钱十",
             random_date(2023, 2025), "-", 0, tag,
             qty, f"KEY-{len(sw_ids)+1:06d}"))
        sw_ids.append(cur.lastrowid)
    db.commit()

    print("9. 建立服务器与软件资产关联...")
    # 获取所有服务器
    servers = db.execute("SELECT id FROM devices WHERE device_type_id=?", (rack_server_id,)).fetchall()
    os_sw = sw_ids[:4]  # 操作系统
    db_sw = sw_ids[4:8]  # 数据库
    mw_sw = sw_ids[8:11]  # 中间件

    for srv in servers:
        srv_id = srv[0]
        # 每台服务器关联一个操作系统
        cur.execute("INSERT OR IGNORE INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type) VALUES(?,?,?,?,?)",
                   (srv_id, 'device', random.choice(os_sw), 'device', 'runs_on'))
        # 50%概率关联一个数据库
        if random.random() > 0.5:
            cur.execute("INSERT OR IGNORE INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type) VALUES(?,?,?,?,?)",
                       (srv_id, 'device', random.choice(db_sw), 'device', 'runs_on'))
        # 30%概率关联一个中间件
        if random.random() > 0.7:
            cur.execute("INSERT OR IGNORE INTO ci_relationships(source_id, source_type, target_id, target_type, rel_type) VALUES(?,?,?,?,?)",
                       (srv_id, 'device', random.choice(mw_sw), 'device', 'runs_on'))
    db.commit()

    print("9. 创建办公资产...")
    office_count = 0
    for room_name, rid in room_ids.items():
        # 台式机
        for i in range(1, 11):
            cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
                lifecycle_state_id, department, custodian, rack_date, warranty_date,
                purchase_price, tag, created_by, room_id, user_name)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                (f"PC-{room_name[:2]}-{i:03d}", desktop_id, "Dell", "OptiPlex 7010",
                 random_serial("PC", office_count + i), "-", "-", random_mac(),
                 None, "-", 1, running_id, "技术部", random.choice(custodians),
                 random_date(2023, 2025), random_date(2026, 2028),
                 random.randint(4000, 8000), "办公,台式机", rid,
                 f"员工{random.randint(100,999)}"))
        office_count += 10

        # 笔记本
        for i in range(1, 6):
            cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
                lifecycle_state_id, department, custodian, rack_date, warranty_date,
                purchase_price, tag, created_by, room_id, user_name)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                (f"NB-{room_name[:2]}-{i:03d}", laptop_id, "HP", "EliteBook 840",
                 random_serial("NB", office_count + i), "-", "-", random_mac(),
                 None, "-", 1, running_id, "开发部", random.choice(custodians),
                 random_date(2023, 2025), random_date(2026, 2028),
                 random.randint(6000, 12000), "办公,笔记本", rid,
                 f"员工{random.randint(100,999)}"))
        office_count += 5

        # 打印机
        for i in range(1, 3):
            cur.execute("""INSERT INTO devices(name, device_type_id, brand, model, serial_number,
                biz_ip, oob_ip, mac_address, cabinet_id, u_position, u_height,
                lifecycle_state_id, department, custodian, rack_date, warranty_date,
                purchase_price, tag, created_by, room_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (f"PR-{room_name[:2]}-{i:03d}", printer_id, "HP", "LaserJet Pro M404",
                 random_serial("PR", office_count + i), "-", "-", random_mac(),
                 None, "-", 1, running_id, "行政部", random.choice(custodians),
                 random_date(2022, 2024), random_date(2025, 2027),
                 random.randint(2000, 5000), "办公,打印", rid))
        office_count += 2
    db.commit()

    print("10. 创建业务系统...")
    systems_data = [
        ("核心交易系统", "技术部", "张三", "核心业务交易处理系统", "交易核心", "Java/Spring Boot"),
        ("客户管理系统", "市场部", "王五", "客户关系管理系统", "客户管理", "Python/Django"),
        ("数据仓库", "数据部", "钱七", "企业数据仓库和BI分析平台", "数据分析", "Spark/Flink"),
        ("监控平台", "运维部", "周九", "统一监控告警平台", "运维监控", "Go/Grafana"),
        ("OA系统", "行政部", "郑十一", "企业办公自动化系统", "办公协作", "Java/Spring"),
        ("灾备切换系统", "运维部", "吴十", "同城灾备自动切换系统", "灾备", "Go/Ansible"),
        ("日志分析平台", "运维部", "钱十", "集中日志采集与分析", "日志", "ELK Stack"),
        ("安全审计系统", "安全组", "孙七", "网络安全审计与合规", "安全", "Java/Spring"),
    ]

    for name, dept, owner, desc, domain, tech in systems_data:
        # 根据系统名称分配到机房
        if "灾备" in name:
            rid = room_ids["天津灾备机房"]
        elif "交易" in name or "核心" in name:
            rid = room_ids["金桥核心交易机房"]
        elif "同城" in name:
            rid = room_ids["宁桥路同城机房"]
        else:
            rid = room_ids["陆家嘴管理机房"]

        cur.execute("""INSERT INTO business_systems(name, sys_type, status, department, owner,
            developer, description, biz_domain, tech_stack, db_info, middleware,
            deploy_path, source_repo, monitor_url, created_by)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (name, "业务系统", "running", dept, owner, "开发组",
             desc, domain, tech, "MySQL 8.0", "Nginx/Tomcat",
             f"/opt/app/{name}", f"git@git.company.com:{name}.git",
             f"http://monitor.company.com/{name}"))

        # 关联设备到系统（随机选择该机房的几台服务器）
        sys_id = cur.lastrowid
        devs = db.execute("SELECT id FROM devices WHERE room_id=? AND device_type_id=? LIMIT 5",
                         (rid, rack_server_id)).fetchall()
        for d in devs:
            cur.execute("INSERT OR IGNORE INTO system_device_rel(system_id, device_id, role) VALUES(?,?,?)",
                       (sys_id, d[0], random.choice(["生产", "测试", "开发"])))
    db.commit()

    print("11. 创建操作日志...")
    devices_sample = db.execute("SELECT id, name FROM devices ORDER BY RANDOM() LIMIT 20").fetchall()
    for dev_id, dev_name in devices_sample:
        action = random.choice(["部署上线", "配置变更", "固件升级", "状态变更", "扩容操作"])
        cur.execute("INSERT INTO device_logs(device_id, user_id, action, detail, created_at) VALUES(?,?,?,?,?)",
                   (dev_id, 1, action, f"{action}: {dev_name}", random_date(2024, 2025)))
    db.commit()

    print("12. 创建系统日志...")
    system_logs = [
        ("INFO", "认证", "用户登录", "admin 登录成功"),
        ("INFO", "资产管理", "新增设备", "批量导入设备"),
        ("INFO", "IP管理", "新增地址池", "创建业务地址池"),
        ("INFO", "机房管理", "新增机房", "新增陆家嘴管理机房"),
        ("INFO", "业务系统", "新增系统", "新增核心交易系统"),
    ]
    for level, module, action, detail in system_logs:
        cur.execute("INSERT INTO system_logs(level, module, action, detail, username, ip) VALUES(?,?,?,?,?,?)",
                   (level, module, action, detail, "admin", "127.0.0.1"))
    db.commit()

    # 统计
    total_devices = cur.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    total_rooms = cur.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    total_cabinets = cur.execute("SELECT COUNT(*) FROM cabinets").fetchone()[0]
    total_pools = cur.execute("SELECT COUNT(*) FROM ip_pools").fetchone()[0]
    total_segments = cur.execute("SELECT COUNT(*) FROM ip_pool_segments").fetchone()[0]
    total_ips = cur.execute("SELECT COUNT(*) FROM ip_addresses").fetchone()[0]
    total_systems = cur.execute("SELECT COUNT(*) FROM business_systems").fetchone()[0]

    print(f"\n数据生成完成！")
    print(f"  机房: {total_rooms} 个")
    print(f"  机柜: {total_cabinets} 个")
    print(f"  设备: {total_devices} 台")
    print(f"  地址池: {total_pools} 个")
    print(f"  网段: {total_segments} 个")
    print(f"  IP地址: {total_ips} 个")
    print(f"  业务系统: {total_systems} 个")

    db.close()


if __name__ == "__main__":
    seed()
