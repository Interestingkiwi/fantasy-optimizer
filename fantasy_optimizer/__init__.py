from flask import Flask
from .config import Config
from .auth import oauth  # Assuming your OAuth setup is here

def create_app():
    app = Flask(__name__, static_folder='../static', template_folder='..')
    app.config.from_object(Config)

    # Initialize extensions
    oauth.init_app(app)

    # Import and register blueprints
    from .routes import api_bp
    app.register_blueprint(api_bp)

    return app
