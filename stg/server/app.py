from flask import Flask, jsonify

# Initialize the Flask application
app = Flask(__name__)

@app.route("/")
def home():
    """Home endpoint to confirm the server is running."""
    return "H2H Fantasy Optimizer Backend is running!"

@app.route("/api/data")
def get_data():
    """A sample API endpoint."""
    # This is where you might fetch data from Yahoo's API in the future
    sample_data = {
        "message": "This is sample data from the server."
    }
    return jsonify(sample_data)

# This allows the script to be run directly
if __name__ == "__main__":
    # In a production environment, you would use a proper WSGI server like Gunicorn
    app.run(debug=True)
