"""
This file marks the 'fantasy_optimizer' directory as a Python package.
It contains the application factory function, create_app(), which is responsible
for initializing the Flask app, configuring it, and registering blueprints.
"""
from flask import Flask
from flask_cors import CORS
from . import config

def create_app():
    """
    Application factory function. Creates and configures the Flask app.

    The static_folder='../static' tells Flask that the folder for static files
    (like JS, CSS) is one level up from this file's directory. This is necessary
    because the app is structured as a package.
    """
    app = Flask(__name__, static_folder='../static')
    app.config['SECRET_KEY'] = config.SECRET_KEY
    CORS(app)

    # Import and register blueprints.
    from . import routes
    from . import auth
    app.register_blueprint(routes.api_bp)
    app.register_blueprint(auth.auth_bp)

    return app
