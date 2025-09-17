"""
Handles authentication for the application.
It defines the basic HTTP authentication mechanism and the password verification logic.
"""
from flask_httpauth import HTTPBasicAuth
from .config import USERS

# Initialize the HTTPBasicAuth extension
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    """
    Callback function used by Flask-HTTPAuth to verify a user's credentials.
    Checks if the provided username exists in the USERS dictionary and if the
    password matches.
    """
    if username in USERS and USERS[username] == password:
        return username
    return None
