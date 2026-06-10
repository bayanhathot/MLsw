from flask import flask

def create_app():
    app = flask(__name__)
    # Secret key to secure sessions and cookies.
    # It can be any random string, but it must be kept secret.
    app.config['SECRET_KEY'] = 'jfdnosandg fsghaajsfgas'

    from .views import views
    from .auth import auth

    # Register the blueprints with the Flask app
    # You can specify a URL prefix for each blueprint if you want.
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')

    # MONGODB ADDITION.
    from pymongo import MongoClient
    from .models import ProductModel
    app.config["MONGO_URI"] = "mongodb://db:27017/db"
    app.mongo = MongoClient(app.config["MONGO_URI"])
    app.mongo.products = ProductModel(app.mongo.mydb.products)

    return app