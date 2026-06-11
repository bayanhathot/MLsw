from flask import Flask, jsonify
import time


def error_response(code, message):
    return jsonify({
        "error": {
            "http_status": code,
            "message": message
        }
    }), code


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "secret-key"

    app.start_time = time.time()
    app.users = {}
    app.tokens = {}
    app.stats = {"success": 0, "fail": 0}
    app.model_ready = True

    from .views import views
    from .auth import auth

    app.register_blueprint(views, url_prefix="/")
    app.register_blueprint(auth, url_prefix="/")

    @app.errorhandler(400)
    def bad_request(error):
        return error_response(400, "Malformed request")

    @app.errorhandler(401)
    def unauthorized(error):
        return error_response(401, "Missing or invalid token")

    @app.errorhandler(404)
    def not_found(error):
        return error_response(404, "Not found")

    @app.errorhandler(405)
    def method_not_allowed(error):
        return error_response(405, "Unsupported http method")

    @app.errorhandler(500)
    def internal_server_error(error):
        return error_response(500, "Internal server error")

    return app