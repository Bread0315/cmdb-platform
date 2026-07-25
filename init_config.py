"""
CMDB Platform - 初始化配置管理
"""
import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".init_config.json")


def is_initialized():
    """检查系统是否已初始化"""
    return os.path.exists(CONFIG_FILE)


def get_db_config():
    """获取数据库配置"""
    if not is_initialized():
        return None
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_db_config(db_type, **kwargs):
    """保存数据库配置"""
    config = {"db_type": db_type}
    if db_type == "mysql":
        config["mysql_host"] = kwargs.get("host", "127.0.0.1")
        config["mysql_port"] = kwargs.get("port", 3306)
        config["mysql_user"] = kwargs.get("user", "root")
        config["mysql_password"] = kwargs.get("password", "")
        config["mysql_database"] = kwargs.get("database", "cmdb")
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_db_url():
    """根据配置获取数据库连接URL"""
    config = get_db_config()
    if not config:
        # 默认使用SQLite
        from config import DB_PATH
        return f"sqlite:///{DB_PATH}"

    if config["db_type"] == "mysql":
        host = config.get("mysql_host", "127.0.0.1")
        port = config.get("mysql_port", 3306)
        user = config.get("mysql_user", "root")
        password = config.get("mysql_password", "")
        database = config.get("mysql_database", "cmdb")
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    else:
        from config import DB_PATH
        return f"sqlite:///{DB_PATH}"
