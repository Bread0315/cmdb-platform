"""
CMDB Platform - 配置管理
"""
import os
import logging
import logging.handlers
import json
from datetime import timedelta

# 加载 .env 配置
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --------------- 安全配置常量 ---------------
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
PASSWORD_MIN_LENGTH = 8
PASSWORD_MIN_LENGTH_ADMIN = 8
PASSWORD_MIN_LENGTH_USER = 12
PASSWORD_EXPIRY_DAYS = 90
SESSION_TIMEOUT_HOURS = 8

# --------------- 路径配置 ---------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cmdb.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
INIT_CONFIG_FILE = os.path.join(BASE_DIR, ".init_config.json")
os.makedirs(LOG_DIR, exist_ok=True)


def is_initialized():
    """检查系统是否已初始化"""
    return os.path.exists(INIT_CONFIG_FILE)


def get_db_config():
    """获取数据库配置"""
    if not os.path.exists(INIT_CONFIG_FILE):
        return {"db_type": "sqlite"}
    with open(INIT_CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_mysql_config():
    """获取MySQL配置"""
    config = get_db_config()
    if config.get("db_type") == "mysql":
        return {
            "host": config.get("mysql_host", "127.0.0.1"),
            "port": config.get("mysql_port", 3306),
            "user": config.get("mysql_user", "root"),
            "password": config.get("mysql_password", ""),
            "database": config.get("mysql_database", "cmdb"),
        }
    return None


# --------------- 安全日志系统 ---------------
class SafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """安全的日志轮转处理器，忽略文件锁定错误"""
    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass
        except Exception:
            pass


def setup_logging():
    """配置文件日志和控制台日志"""
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    app_logger = logging.getLogger('cmdb')
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        app_handler = SafeTimedRotatingFileHandler(
            os.path.join(LOG_DIR, 'app.log'), when='midnight', interval=1, backupCount=30, encoding='utf-8'
        )
        app_handler.setFormatter(fmt)
        app_logger.addHandler(app_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        app_logger.addHandler(console_handler)

        error_handler = SafeTimedRotatingFileHandler(
            os.path.join(LOG_DIR, 'error.log'), when='midnight', interval=1, backupCount=60, encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(fmt)
        app_logger.addHandler(error_handler)

    access_logger = logging.getLogger('cmdb.access')
    access_logger.setLevel(logging.INFO)
    if not access_logger.handlers:
        access_handler = SafeTimedRotatingFileHandler(
            os.path.join(LOG_DIR, 'access.log'), when='midnight', interval=1, backupCount=30, encoding='utf-8'
        )
        access_fmt = logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        access_handler.setFormatter(access_fmt)
        access_logger.addHandler(access_handler)

    return app_logger, access_logger

logger, access_logger = setup_logging()
