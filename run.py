"""
This is the main entry point to run the Flask application.
It creates the app using the factory function in the fantasy_optimizer package
and runs it.
"""
from fantasy_optimizer import create_app

# Create the Flask app instance using the app factory
app = create_app()

if __name__ == '__main__':
    # Run the app in debug mode for development
    # In a production environment, you would use a WSGI server like Gunicorn
    app.run(debug=True)
