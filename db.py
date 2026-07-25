"""
CMDB Platform - 数据库管理（支持 SQLite / MySQL）
"""
import sqlite3
import os
from flask import g
from werkzeug.security import generate_password_hash
from config import DB_PATH, get_db_config, get_mysql_config, logger


def get_db():
    """获取数据库连接"""
    if "db" not in g:
        config = get_db_config()
        if config.get("db_type") == "mysql":
            import pymysql
            mysql_cfg = get_mysql_config()
            conn = pymysql.connect(
                host=mysql_cfg["host"],
                port=mysql_cfg["port"],
                user=mysql_cfg["user"],
                password=mysql_cfg["password"],
                database=mysql_cfg["database"],
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
            g.db = conn
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA journal_mode=WAL")
            g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(exc):
    """关闭数据库连接"""
    db = g.pop("db", None)
    if db:
        db.close()


def execute_query(db, sql, params=(), one=False):
    """统一查询接口（兼容 SQLite 和 MySQL）"""
    config = get_db_config()
    if config.get("db_type") == "mysql":
        cur = db.cursor()
        cur.execute(sql, params)
        if one:
            return cur.fetchone()
        return cur.fetchall()
    else:
        if one:
            return db.execute(sql, params).fetchone()
        return db.execute(sql, params).fetchall()


def execute_insert(db, sql, params=()):
    """统一插入接口"""
    config = get_db_config()
    if config.get("db_type") == "mysql":
        cur = db.cursor()
        cur.execute(sql, params)
        db.commit()
        return cur.lastrowid
    else:
        cur = db.execute(sql, params)
        db.commit()
        return cur.lastrowid


def init_db():
    """初始化数据库表结构和默认数据"""
    config = get_db_config()
    if config.get("db_type") == "mysql":
        _init_mysql_default_data()
    else:
        _init_sqlite_default_data()


def _init_sqlite_default_data():
    """SQLite 初始化"""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT    NOT NULL UNIQUE,
        password    TEXT    NOT NULL,
        real_name   TEXT    DEFAULT '',
        email       TEXT    DEFAULT '',
        role        TEXT    NOT NULL DEFAULT 'user',
        is_active   INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 1,
        password_changed_at TEXT DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS device_types (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT    NOT NULL UNIQUE,
        category TEXT   NOT NULL DEFAULT 'other'
    );
    CREATE TABLE IF NOT EXISTS lifecycle_states (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        sort INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS devices (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        device_type_id  INTEGER NOT NULL REFERENCES device_types(id),
        brand           TEXT    DEFAULT '',
        model           TEXT    DEFAULT '',
        serial_number   TEXT    DEFAULT '',
        biz_ip          TEXT    DEFAULT '',
        oob_ip          TEXT    DEFAULT '',
        mac_address     TEXT    DEFAULT '',
        cabinet_id      INTEGER REFERENCES cabinets(id) ON DELETE SET NULL,
        u_position      TEXT    DEFAULT '',
        u_height        INTEGER NOT NULL DEFAULT 1,
        location        TEXT    DEFAULT '',
        department      TEXT    DEFAULT '',
        custodian       TEXT    DEFAULT '',
        purchase_date   TEXT    DEFAULT '',
        rack_date       TEXT    DEFAULT '',
        warranty_date   TEXT    DEFAULT '',
        purchase_price  REAL    DEFAULT 0,
        lifecycle_state_id INTEGER NOT NULL REFERENCES lifecycle_states(id),
        remark          TEXT    DEFAULT '',
        tag             TEXT    DEFAULT '',
        created_by      INTEGER REFERENCES users(id),
        created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS rooms (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        building    TEXT    DEFAULT '',
        floor       TEXT    DEFAULT '',
        area        TEXT    DEFAULT '',
        remark      TEXT    DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS cabinets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id     INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
        name        TEXT    NOT NULL,
        u_total     INTEGER NOT NULL DEFAULT 42,
        power       TEXT    DEFAULT '',
        remark      TEXT    DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS device_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        user_id     INTEGER REFERENCES users(id),
        action      TEXT    NOT NULL,
        detail      TEXT    DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS login_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT    NOT NULL,
        ip          TEXT    DEFAULT '',
        success     INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS ip_pools (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL DEFAULT '',
        remark      TEXT    DEFAULT '',
        created_by  INTEGER REFERENCES users(id),
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS ip_pool_segments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        pool_id     INTEGER NOT NULL REFERENCES ip_pools(id) ON DELETE CASCADE,
        network     TEXT    NOT NULL,
        mask        INTEGER NOT NULL,
        gateway     TEXT    DEFAULT '',
        vlan        TEXT    DEFAULT '' UNIQUE,
        room_id     INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
        remark      TEXT    DEFAULT '',
        UNIQUE(pool_id, network, mask)
    );
    CREATE TABLE IF NOT EXISTS ip_addresses (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        pool_id     INTEGER NOT NULL REFERENCES ip_pools(id) ON DELETE CASCADE,
        ip          TEXT    NOT NULL,
        status      TEXT    NOT NULL DEFAULT 'available',
        device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        ip_type     TEXT    DEFAULT '',
        remark      TEXT    DEFAULT '',
        UNIQUE(pool_id, ip)
    );
    CREATE TABLE IF NOT EXISTS business_systems (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        sys_type        TEXT    DEFAULT '',
        status          TEXT    NOT NULL DEFAULT 'running',
        department      TEXT    DEFAULT '',
        owner           TEXT    DEFAULT '',
        developer       TEXT    DEFAULT '',
        description     TEXT    DEFAULT '',
        biz_domain      TEXT    DEFAULT '',
        tech_stack      TEXT    DEFAULT '',
        db_info         TEXT    DEFAULT '',
        middleware      TEXT    DEFAULT '',
        deploy_path     TEXT    DEFAULT '',
        source_repo     TEXT    DEFAULT '',
        monitor_url     TEXT    DEFAULT '',
        remark          TEXT    DEFAULT '',
        created_by      INTEGER REFERENCES users(id),
        created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS system_device_rel (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        system_id   INTEGER NOT NULL REFERENCES business_systems(id) ON DELETE CASCADE,
        device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        role        TEXT    DEFAULT '',
        UNIQUE(system_id, device_id)
    );
    CREATE TABLE IF NOT EXISTS ci_relationships (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id       INTEGER NOT NULL,
        source_type     TEXT    NOT NULL,
        target_id       INTEGER NOT NULL,
        target_type     TEXT    NOT NULL,
        rel_type        TEXT    NOT NULL DEFAULT 'depends_on',
        remark          TEXT    DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS system_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        level       TEXT    NOT NULL DEFAULT 'INFO',
        module      TEXT    DEFAULT '',
        action      TEXT    NOT NULL,
        detail      TEXT    DEFAULT '',
        username    TEXT    DEFAULT '',
        ip          TEXT    DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    """)

    # 兼容升级
    migrations = [
        ("devices", "u_height", "INTEGER NOT NULL DEFAULT 1"),
        ("devices", "tag", "TEXT DEFAULT ''"),
        ("users", "must_change_password", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "password_changed_at", "TEXT DEFAULT ''"),
        ("devices", "quantity", "INTEGER DEFAULT 1"),
        ("devices", "license_key", "TEXT DEFAULT ''"),
        ("devices", "asset_code", "TEXT DEFAULT ''"),
        ("devices", "user_name", "TEXT DEFAULT ''"),
        ("devices", "room_id", "INTEGER REFERENCES rooms(id) ON DELETE SET NULL"),
        ("rooms", "location", "TEXT DEFAULT ''"),
        ("devices", "rack_date", "TEXT DEFAULT ''"),
    ]
    for table, column, col_def in migrations:
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            db.commit()
        except sqlite3.OperationalError:
            pass

    # 迁移：将 purchase_date 数据复制到 rack_date
    try:
        db.execute("UPDATE devices SET rack_date = purchase_date WHERE rack_date = '' AND purchase_date != ''")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # 设备类型
    cur = db.cursor()
    types = [
        ("机架服务器", "hardware"), ("塔式服务器", "hardware"), ("刀片服务器", "hardware"),
        ("存储设备", "hardware"), ("负载均衡", "hardware"), ("KVM切换器", "hardware"),
        ("交换机", "network"), ("路由器", "network"), ("防火墙", "network"),
        ("无线AP", "network"), ("VPN设备", "network"),
        ("UPS电源", "infrastructure"), ("PDU电源", "infrastructure"),
        ("配电柜", "infrastructure"), ("精密空调", "infrastructure"),
        ("发电机", "infrastructure"), ("消防设备", "infrastructure"),
        ("动环监控", "infrastructure"), ("配线架", "infrastructure"),
        ("光纤交换机", "infrastructure"), ("机柜配件", "infrastructure"),
        ("操作系统", "software"), ("数据库", "software"), ("中间件", "software"),
        ("虚拟化平台", "software"), ("容器平台", "software"), ("监控软件", "software"),
        ("安全软件", "software"), ("备份软件", "software"), ("应用系统", "software"),
        ("台式机", "office"), ("笔记本", "office"), ("显示器", "office"),
        ("打印机", "office"), ("投影仪", "office"), ("会议设备", "office"),
        ("光模块", "other"), ("网卡", "other"), ("硬盘", "other"),
        ("内存", "other"), ("CPU", "other"),
    ]
    for name, cat in types:
        cur.execute("INSERT OR IGNORE INTO device_types(name, category) VALUES(?, ?)", (name, cat))

    states = [("运行中", 1), ("已下架", 2), ("已报废", 3)]
    for name, sort in states:
        cur.execute("INSERT OR IGNORE INTO lifecycle_states(name, sort) VALUES(?, ?)", (name, sort))

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users(username, password, real_name, role, must_change_password) VALUES(?,?,?,?,1)",
            ("admin", generate_password_hash("admin123"), "系统管理员", "admin")
        )

    db.commit()
    _add_indexes_sqlite(db)
    db.close()


def _init_mysql_default_data():
    """MySQL 初始化默认数据"""
    mysql_cfg = get_mysql_config()
    import pymysql
    conn = pymysql.connect(
        host=mysql_cfg["host"], port=mysql_cfg["port"],
        user=mysql_cfg["user"], password=mysql_cfg["password"],
        database=mysql_cfg["database"],
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
    )
    cur = conn.cursor()

    # 检查是否已有数据
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()['cnt'] == 0:
        from werkzeug.security import generate_password_hash
        cur.execute(
            "INSERT INTO users(username, password, real_name, role, must_change_password) VALUES(%s,%s,%s,%s,1)",
            ("admin", generate_password_hash("admin123"), "系统管理员", "admin")
        )

    cur.execute("SELECT COUNT(*) as cnt FROM device_types")
    if cur.fetchone()['cnt'] == 0:
        types = [
            ("机架服务器", "hardware"), ("塔式服务器", "hardware"), ("刀片服务器", "hardware"),
            ("存储设备", "hardware"), ("负载均衡", "hardware"), ("KVM切换器", "hardware"),
            ("交换机", "network"), ("路由器", "network"), ("防火墙", "network"),
            ("无线AP", "network"), ("VPN设备", "network"),
            ("UPS电源", "infrastructure"), ("PDU电源", "infrastructure"),
            ("配电柜", "infrastructure"), ("精密空调", "infrastructure"),
            ("发电机", "infrastructure"), ("消防设备", "infrastructure"),
            ("动环监控", "infrastructure"), ("配线架", "infrastructure"),
            ("光纤交换机", "infrastructure"), ("机柜配件", "infrastructure"),
            ("操作系统", "software"), ("数据库", "software"), ("中间件", "software"),
            ("虚拟化平台", "software"), ("容器平台", "software"), ("监控软件", "software"),
            ("安全软件", "software"), ("备份软件", "software"), ("应用系统", "software"),
            ("台式机", "office"), ("笔记本", "office"), ("显示器", "office"),
            ("打印机", "office"), ("投影仪", "office"), ("会议设备", "office"),
            ("光模块", "other"), ("网卡", "other"), ("硬盘", "other"),
            ("内存", "other"), ("CPU", "other"),
        ]
        for name, cat in types:
            cur.execute("INSERT IGNORE INTO device_types(name, category) VALUES(%s, %s)", (name, cat))

    cur.execute("SELECT COUNT(*) as cnt FROM lifecycle_states")
    if cur.fetchone()['cnt'] == 0:
        states = [("运行中", 1), ("已下架", 2), ("已报废", 3)]
        for name, sort in states:
            cur.execute("INSERT IGNORE INTO lifecycle_states(name, sort) VALUES(%s, %s)", (name, sort))

    conn.commit()
    conn.close()


def _add_indexes_sqlite(db):
    """SQLite 添加索引"""
    indexes = [
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_asset_code ON devices(asset_code) WHERE asset_code != ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_serial_number ON devices(serial_number) WHERE serial_number != ''",
        "CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type_id)",
        "CREATE INDEX IF NOT EXISTS idx_devices_state ON devices(lifecycle_state_id)",
        "CREATE INDEX IF NOT EXISTS idx_devices_cabinet ON devices(cabinet_id)",
        "CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices(biz_ip)",
        "CREATE INDEX IF NOT EXISTS idx_device_logs_device ON device_logs(device_id)",
        "CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(username, success)",
        "CREATE INDEX IF NOT EXISTS idx_ip_addresses_pool ON ip_addresses(pool_id)",
        "CREATE INDEX IF NOT EXISTS idx_ip_addresses_status ON ip_addresses(status)",
        "CREATE INDEX IF NOT EXISTS idx_system_device_system ON system_device_rel(system_id)",
        "CREATE INDEX IF NOT EXISTS idx_system_device_device ON system_device_rel(device_id)",
        "CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level)",
        "CREATE INDEX IF NOT EXISTS idx_system_logs_created ON system_logs(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_cabinets_room ON cabinets(room_id)",
    ]
    for sql in indexes:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass
    db.commit()


def log_to_db(db, level, module, action, detail, username=None, ip=None):
    """写入数据库系统日志"""
    from flask import session, request
    config = get_db_config()
    if config.get("db_type") == "mysql":
        db.execute(
            "INSERT INTO system_logs(level, module, action, detail, username, ip) VALUES(%s,%s,%s,%s,%s,%s)",
            (level, module, action, detail, username or session.get('username', '-'), ip or request.remote_addr or '-')
        )
    else:
        db.execute(
            "INSERT INTO system_logs(level, module, action, detail, username, ip) VALUES(?,?,?,?,?,?)",
            (level, module, action, detail, username or session.get('username', '-'), ip or request.remote_addr or '-')
        )
