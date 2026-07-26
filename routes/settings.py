"""
CMDB Platform - 系统设置
"""
import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import admin_required
from db import get_db, log_to_db
from config import logger

settings_bp = Blueprint('settings', __name__)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.settings.json')

DEFAULT_SETTINGS = {
    'system_name': 'CMDB 资产管理平台',
    'session_timeout': 30,
    'password_expiry_days': 90,
    'max_login_attempts': 5,
    'lockout_minutes': 15,
    'password_min_length': 8,
    'require_uppercase': True,
    'require_lowercase': True,
    'require_number': True,
    'require_special': False,
    'log_retention_days': 90,
    'warranty_alert_days': 30,
    'ip_usage_alert_threshold': 80,
    'cabinet_usage_alert_threshold': 90,
    'temperature_alert_high': 28,
    'temperature_alert_low': 18,
    'humidity_alert_high': 70,
    'humidity_alert_low': 30,
}


def load_settings():
    """加载系统设置"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                settings = DEFAULT_SETTINGS.copy()
                settings.update(saved)
                return settings
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """保存系统设置"""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


@settings_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    db = get_db()
    settings = load_settings()

    if request.method == "POST":
        # 读取表单数据
        settings['system_name'] = request.form.get("system_name", "").strip() or 'CMDB 资产管理平台'
        settings['session_timeout'] = int(request.form.get("session_timeout", 30))
        settings['password_expiry_days'] = int(request.form.get("password_expiry_days", 90))
        settings['max_login_attempts'] = int(request.form.get("max_login_attempts", 5))
        settings['lockout_minutes'] = int(request.form.get("lockout_minutes", 15))
        settings['password_min_length'] = int(request.form.get("password_min_length", 8))
        settings['require_uppercase'] = 'require_uppercase' in request.form
        settings['require_lowercase'] = 'require_lowercase' in request.form
        settings['require_number'] = 'require_number' in request.form
        settings['require_special'] = 'require_special' in request.form
        settings['log_retention_days'] = int(request.form.get("log_retention_days", 90))
        settings['warranty_alert_days'] = int(request.form.get("warranty_alert_days", 30))
        settings['ip_usage_alert_threshold'] = int(request.form.get("ip_usage_alert_threshold", 80))
        settings['cabinet_usage_alert_threshold'] = int(request.form.get("cabinet_usage_alert_threshold", 90))
        settings['temperature_alert_high'] = int(request.form.get("temperature_alert_high", 28))
        settings['temperature_alert_low'] = int(request.form.get("temperature_alert_low", 18))
        settings['humidity_alert_high'] = int(request.form.get("humidity_alert_high", 70))
        settings['humidity_alert_low'] = int(request.form.get("humidity_alert_low", 30))

        save_settings(settings)
        log_to_db(db, 'INFO', '系统设置', '更新设置', '管理员更新了系统设置')
        db.commit()
        flash("系统设置已保存", "success")
        return redirect(url_for("settings.settings"))

    return render_template("settings.html", settings=settings)


@settings_bp.route("/api/settings")
@admin_required
def api_settings():
    """API: 获取系统设置"""
    return load_settings()
