from flask import Flask
import time

from .utils import error_response


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "secret-key"

    app.start_time = time.time()

    # In-memory storage.
    # This is okay for this homework unless they specifically require persistence.
    app.users = {}
    app.tokens = {}

    # Counts only /register, /login, /logout, /classifier
    app.stats = {
        "success": 0,
        "fail": 0
    }

    # Used by /status
    app.model_ready = True

    from .views import views
    from .auth import auth

    app.register_blueprint(views)
    app.register_blueprint(auth)

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