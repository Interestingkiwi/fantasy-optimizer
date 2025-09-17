"""
Configuration settings for the Fantasy Hockey Matchup Optimizer application.
This file centralizes all the configuration variables.
"""
import os

# --- Core App Config ---
# This block writes the environment variable to a file if it exists.
# This is crucial for deployment environments like Render.
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

# --- Yahoo API Config ---
YAHOO_LEAGUE_KEY = '453.l.2200'

# --- Security/Auth Config ---
# Set your desired username and password here for the live app
USERS = {
    "your_username": "your_passwowrd",
    "4": ""
}
