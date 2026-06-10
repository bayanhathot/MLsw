from flask import Blueprint
auth = Blueprint('auth', __name__)
@auth.route('/login')
def login():
# Return a simple HTML response for the login page
#200 is the "OK" HTTP status code
    return "<h1>Login</h1><p>This is the login page!</p>"
@auth.route('/logout')
def logout():
# Return a simple HTML response for the logout page
#200 is the "OK" HTTP status code
    return "<h1>Logout</h1><p>This is the logout page!</p>", 200
@auth.route('/sign-up')
def sign_up():
# Return a simple HTML response for the signup page
#200 is the "OK" HTTP status code
    return "<h1>Signup</h1><p>This is the signup page!</p>", 200