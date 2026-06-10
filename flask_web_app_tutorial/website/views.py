from flask import Blueprint, render_template_string, render_template

# Blueprint lets us organize routes into different files
# we don't have to put all routes in the "views.py" module
views = Blueprint('views', __name__)

# Define the routes for the views blueprint
@views.route('/')

def home():
    """
    Return a simple HTML response for the home page.
    200 is the 'OK' HTTP status code.
    """
    html_content = """
    <h1>Home</h1>
    <p>Welcome to the home page!</p>
    """
    return render_template('home.html'), 200
@views.route('/about')
def about():
    """
    Return a simple HTML response for the about page.
    200 is the 'OK' HTTP status code.
    """
    html_content = """
    <h1>About</h1>
    <p>This is the about page!</p>
    """
    return render_template_string(html_content), 200
@views.route('/status')
def status():
    return {"version": "1.0", "status": "OK"}, 200
@views.route('/secret')
def secret():
# This will always return an error (We don't have a login system yet!)
# 401 is the HTTP status code for "Unauthorized"
    return {"error": {"http_status": 401, "message": "You are not logged in"}}, 401