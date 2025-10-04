"""
This file marks the 'fantasy_optimizer' directory as a Python package.
It contains the application factory function, create_app(), which is responsible
for initializing the Flask app, configuring it, and registering blueprints.
"""
import os
from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    """
    Application factory function. Creates and configures the Flask app.
    """
    # Define a more robust, absolute path for the static folder
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
    app = Flask(__name__, static_folder=static_dir)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key_should_be_changed')

    CORS(app, supports_credentials=True)

    # Import and register blueprints
    from . import routes
    from . import auth
    app.register_blueprint(routes.api_bp)
    app.register_blueprint(auth.auth_bp)

    return app
