from flask import Flask
import time

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

    return app
