from website import create_app
import argparse

app = create_app()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the Flask server.')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()

    # Debug mode: the server will restart automatically when code changes
    # Do not use debug mode in production
    app.run(debug=True, host='0.0.0.0', port=args.port)