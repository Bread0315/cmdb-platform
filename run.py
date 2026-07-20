#!/usr/bin/env python3
"""
CMDB Platform - 启动脚本
跨平台开箱即用，支持 Windows / Linux / macOS
"""
import os
import sys

def main():
    """启动 CMDB 平台"""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    try:
        import flask
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        sys.exit(1)

    host = os.environ.get("CMDB_HOST", "0.0.0.0")
    port = int(os.environ.get("CMDB_PORT", "5000"))
    debug = os.environ.get("CMDB_DEBUG", "true").lower() in ("true", "1", "yes")

    print("=" * 60)
    print("  CMDB Platform - IT Asset Management")
    print("=" * 60)
    print(f"  URL:   http://127.0.0.1:{port}")
    print(f"  Debug: {'ON' if debug else 'OFF'}")
    print("=" * 60)
    print()

    from db import init_db
    from app import app

    init_db()
    app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    main()
