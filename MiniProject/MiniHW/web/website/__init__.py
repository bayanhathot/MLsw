from flask import Flask

from .routes import bp as routes_bp
from .store import JsonUserStore, ProcessedStats, SessionStore
from .utils import json_error, should_count_endpoint_failure


def create_app():
    app = Flask(__name__)
    app.config.from_prefixed_env()
    app.config.setdefault("SECRET_KEY", "dev-secret-key-change-me")

    app.extensions["users"] = JsonUserStore("instance/users.json")
    app.extensions["sessions"] = SessionStore()
    app.extensions["stats"] = ProcessedStats()

    app.register_blueprint(routes_bp)

    @app.errorhandler(400)
    def bad_request(error):
        return json_error("Malformed request", 400)

    @app.errorhandler(404)
    def not_found(error):
        return json_error("Endpoint not found", 404)

    @app.errorhandler(405)
    def method_not_allowed(error):
        if should_count_endpoint_failure():
            app.extensions["stats"].increment_fail()
        return json_error("Unsupported http method", 405)

    @app.errorhandler(500)
    def internal_server_error(error):
        return json_error("Internal server error", 500)

    return app
