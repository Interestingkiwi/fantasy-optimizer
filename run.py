"""
This is the main entry point to run the Flask application.
It creates the app using the factory function in the fantasy_optimizer package
and runs it.
"""
from fantasy_optimizer import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
