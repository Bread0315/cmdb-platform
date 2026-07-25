"""
CMDB Platform - 路由模块
"""
from auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.devices import devices_bp
from routes.rooms import rooms_bp
from routes.systems import systems_bp
from routes.users import users_bp
from routes.ip_pools import ip_pools_bp
from routes.api import api_bp
from routes.topology import topology_bp
from routes.logs import logs_bp


def register_routes(app):
    """注册所有路由蓝图"""
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(systems_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(ip_pools_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(topology_bp)
    app.register_blueprint(logs_bp)
