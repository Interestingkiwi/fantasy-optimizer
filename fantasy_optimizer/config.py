"""
Configuration settings for the Fantasy Hockey Matchup Optimizer application.
This file centralizes all the configuration variables.
"""
import os

# --- Core App Config ---
# IMPORTANT: You must set a secret key for session management.
# You can generate a good one using: python -c 'import os; print(os.urandom(24))'
SECRET_KEY = os.environ.get('SECRET_KEY', 'your_default_secret_key_change_me')


# This block writes the environment variable to a file if it exists.
# This is crucial for deployment environments like Render.
# This file should ONLY contain your consumer_key and consumer_secret.
YAHOO_CREDENTIALS_FILE = 'private.json'
private_content = os.environ.get('YAHOO_PRIVATE_JSON')
if private_content:
    print("YAHOO_PRIVATE_JSON environment variable found. Writing to file.")
    with open(YAHOO_CREDENTIALS_FILE, 'w') as f:
        f.write(private_content)
else:
    print("YAHOO_PRIVATE_JSON not found. Assuming local private.json file exists.")


# --- Database Config ---
DB_FILE = "projections.db"
