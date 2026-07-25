"""
CMDB Platform - MySQL 数据库初始化
"""
import pymysql


def init_mysql_db(host, port, user, password, database):
    """初始化 MySQL 数据库"""
    # 连接 MySQL（不指定数据库）
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
    )
    cur = conn.cursor()

    # 创建数据库
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute(f"USE `{database}`")

    # 创建表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        username    VARCHAR(50) NOT NULL UNIQUE,
        password    VARCHAR(255) NOT NULL,
        real_name   VARCHAR(50) DEFAULT '',
        email       VARCHAR(100) DEFAULT '',
        role        VARCHAR(20) NOT NULL DEFAULT 'user',
        is_active   TINYINT NOT NULL DEFAULT 1,
        must_change_password TINYINT NOT NULL DEFAULT 1,
        password_changed_at VARCHAR(30) DEFAULT '',
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS device_types (
        id      INTEGER PRIMARY KEY AUTO_INCREMENT,
        name    VARCHAR(50) NOT NULL UNIQUE,
        category VARCHAR(30) NOT NULL DEFAULT 'other'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lifecycle_states (
        id   INTEGER PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(30) NOT NULL UNIQUE,
        sort INTEGER NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id              INTEGER PRIMARY KEY AUTO_INCREMENT,
        name            VARCHAR(100) NOT NULL,
        device_type_id  INTEGER NOT NULL,
        brand           VARCHAR(50) DEFAULT '',
        model           VARCHAR(50) DEFAULT '',
        serial_number   VARCHAR(100) DEFAULT '',
        biz_ip          VARCHAR(50) DEFAULT '',
        oob_ip          VARCHAR(50) DEFAULT '',
        mac_address     VARCHAR(50) DEFAULT '',
        cabinet_id      INTEGER,
        u_position      VARCHAR(20) DEFAULT '',
        u_height        INTEGER NOT NULL DEFAULT 1,
        location        VARCHAR(100) DEFAULT '',
        department      VARCHAR(50) DEFAULT '',
        custodian       VARCHAR(50) DEFAULT '',
        purchase_date   VARCHAR(20) DEFAULT '',
        rack_date       VARCHAR(20) DEFAULT '',
        warranty_date   VARCHAR(20) DEFAULT '',
        purchase_price  DECIMAL(12,2) DEFAULT 0,
        lifecycle_state_id INTEGER NOT NULL,
        remark          TEXT,
        tag             VARCHAR(200) DEFAULT '',
        created_by      INTEGER,
        created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        quantity        INTEGER DEFAULT 1,
        license_key     VARCHAR(200) DEFAULT '',
        asset_code      VARCHAR(100) DEFAULT '',
        user_name       VARCHAR(50) DEFAULT '',
        room_id         INTEGER,
        INDEX idx_type (device_type_id),
        INDEX idx_state (lifecycle_state_id),
        INDEX idx_cabinet (cabinet_id),
        INDEX idx_serial (serial_number),
        INDEX idx_asset_code (asset_code),
        UNIQUE INDEX idx_serial_unique (serial_number),
        UNIQUE INDEX idx_asset_code_unique (asset_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        name        VARCHAR(100) NOT NULL,
        building    VARCHAR(50) DEFAULT '',
        floor       VARCHAR(20) DEFAULT '',
        area        VARCHAR(50) DEFAULT '',
        remark      TEXT,
        location    VARCHAR(200) DEFAULT '',
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cabinets (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        room_id     INTEGER,
        name        VARCHAR(50) NOT NULL,
        u_total     INTEGER NOT NULL DEFAULT 42,
        power       VARCHAR(50) DEFAULT '',
        remark      TEXT,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_room (room_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS device_logs (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        device_id   INTEGER NOT NULL,
        user_id     INTEGER,
        action      VARCHAR(50) NOT NULL,
        detail      TEXT,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_device (device_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS login_logs (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        username    VARCHAR(50) NOT NULL,
        ip          VARCHAR(50) DEFAULT '',
        success     TINYINT NOT NULL DEFAULT 0,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user (username, success)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ip_pools (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        name        VARCHAR(100) NOT NULL DEFAULT '',
        remark      TEXT,
        created_by  INTEGER,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ip_pool_segments (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        pool_id     INTEGER NOT NULL,
        network     VARCHAR(50) NOT NULL,
        mask        INTEGER NOT NULL,
        gateway     VARCHAR(50) DEFAULT '',
        vlan        VARCHAR(20) DEFAULT '',
        room_id     INTEGER,
        remark      TEXT,
        UNIQUE KEY uk_pool_network (pool_id, network, mask),
        UNIQUE KEY uk_vlan (vlan),
        INDEX idx_pool (pool_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ip_addresses (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        pool_id     INTEGER NOT NULL,
        ip          VARCHAR(50) NOT NULL,
        status      VARCHAR(20) NOT NULL DEFAULT 'available',
        device_id   INTEGER,
        ip_type     VARCHAR(20) DEFAULT '',
        remark      TEXT,
        UNIQUE KEY uk_pool_ip (pool_id, ip),
        INDEX idx_pool (pool_id),
        INDEX idx_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS business_systems (
        id              INTEGER PRIMARY KEY AUTO_INCREMENT,
        name            VARCHAR(100) NOT NULL,
        sys_type        VARCHAR(50) DEFAULT '',
        status          VARCHAR(20) NOT NULL DEFAULT 'running',
        department      VARCHAR(50) DEFAULT '',
        owner           VARCHAR(50) DEFAULT '',
        developer       VARCHAR(50) DEFAULT '',
        description     TEXT,
        biz_domain      VARCHAR(100) DEFAULT '',
        tech_stack      VARCHAR(200) DEFAULT '',
        db_info         VARCHAR(100) DEFAULT '',
        middleware      VARCHAR(100) DEFAULT '',
        deploy_path     VARCHAR(200) DEFAULT '',
        source_repo     VARCHAR(200) DEFAULT '',
        monitor_url     VARCHAR(200) DEFAULT '',
        remark          TEXT,
        created_by      INTEGER,
        created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_device_rel (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        system_id   INTEGER NOT NULL,
        device_id   INTEGER NOT NULL,
        role        VARCHAR(50) DEFAULT '',
        UNIQUE KEY uk_sys_dev (system_id, device_id),
        INDEX idx_system (system_id),
        INDEX idx_device (device_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ci_relationships (
        id              INTEGER PRIMARY KEY AUTO_INCREMENT,
        source_id       INTEGER NOT NULL,
        source_type     VARCHAR(30) NOT NULL,
        target_id       INTEGER NOT NULL,
        target_type     VARCHAR(30) NOT NULL,
        rel_type        VARCHAR(30) NOT NULL DEFAULT 'depends_on',
        remark          TEXT,
        created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
        level       VARCHAR(20) NOT NULL DEFAULT 'INFO',
        module      VARCHAR(50) DEFAULT '',
        action      VARCHAR(50) NOT NULL,
        detail      TEXT,
        username    VARCHAR(50) DEFAULT '',
        ip          VARCHAR(50) DEFAULT '',
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_level (level),
        INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    conn.commit()
    conn.close()
    return True
