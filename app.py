# creates and configures the Flask app.

import json
import os
import secrets

from flask import Flask

from database import close_db, init_db

# Blueprints
from auth import auth_bp
from dashboard import dashboard_bp
from venues import venues_bp
from participants import participants_bp
from arrangements import arrangements_bp
from export_routes import export_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

    app.jinja_env.filters["from_json"] = json.loads

    # close the sqlite connection after each request
    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(arrangements_bp)
    app.register_blueprint(export_bp)

    # uptime check
    @app.route("/api/health")
    def health():
        from flask import jsonify
        return jsonify({"status": "ok", "version": "1.0.0"})

    return app


if __name__ == "__main__":
    init_db()
    print("\n  Smart Seating Layout Design and Planner — dev server")
    print("  → http://127.0.0.1:5000\n")
    application = create_app()
    application.run(debug=True, port=5000)
