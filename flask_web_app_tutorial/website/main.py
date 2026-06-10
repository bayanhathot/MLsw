from website import create_app
app = create_app()
if __name__ == '__main__':
# Debug mode: Every time we make changes to the python code,
# the server will automatically restart.
# (do not use in production)
    app.run(debug=True, host='127.0.0.1', port=5000)
