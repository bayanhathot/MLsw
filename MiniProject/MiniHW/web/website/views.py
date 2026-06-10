from flask import Blueprint, render_template

views = Blueprint('views', __name__)

@views.route('/')
def home():
    return render_template('home.html'),200

@views.route('/about')
def about():
    return "<h1>About</h1><p>This is the about page!</p>"

@views.route('/status')
def status():
    return {"version": "1.0", "status": "OK"}, 200

@views.route('/secret')
def secret():
    return {"error": {"http_status": 401,"message": "You are not logged in"}}, 401

from flask import current_app, redirect, url_for
from pymongo.errors import DuplicateKeyError
from flask import request, jsonify

@views.route("/products")
def products():
    products = current_app.mongo.products.all()
    return render_template("products.html", products=products)

@views.route("/add-product", methods=["POST"])
def add_product():
    # pull form-fields instead of JSON
    name = request.form.get("name")
    price = request.form.get("price")
    try:
        inserted = current_app.mongo.products.insert(name, price)
        return redirect(url_for("views.products"))
    except DuplicateKeyError:
        return jsonify({"error": "product name already exists"}),409

@views.route("/delete-product/<name>", methods=["POST"])
def delete_product(name):
    deleted = current_app.mongo.products.remove(name)
    if deleted:
        return redirect(url_for("views.products"))
    else:
        return jsonify({"error": "not found"}), 404