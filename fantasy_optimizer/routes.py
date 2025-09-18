"""
This module contains all the Flask routes (API endpoints) for the application.
It uses a Flask Blueprint to keep the routes organized and separate from the main
application initialization logic.
"""
import sqlite3
import json
import time
from datetime import date, timedelta, datetime
from flask import Blueprint, jsonify, request, send_from_directory, session
from yahoo_fantasy_api import game
from . import config
from .auth import get_oauth_client
from .data_helpers import get_user_leagues, get_weekly_roster_data, calculate_optimized_totals, get_live_stats_for_team
from .optimization_logic import find_optimal_lineup

# Create a Blueprint. This is Flask's way of organizing groups of related routes.
api_bp = Blueprint('api', __name__)

def check_auth_and_get_game():
    """
    Helper to check session tokens, refresh if necessary, and return an
    authenticated yfa.Game object.
    """
    token_data = session.get('yahoo_token_data')
    if not token_data:
        return None, (jsonify({"error": "User not authenticated"}), 401)

    # Manually check if the token is expired or close to expiring
    expires_in = token_data.get('expires_in', 3600)
    token_time = token_data.get('token_time', 0)

    # Refresh if less than 5 minutes remain
    if time.time() > token_time + expires_in - 300:
        print("Token expired or nearing expiration, attempting to refresh...")
        try:
            # Create the client with the expired token data to access the refresh method
            oauth = get_oauth_client(token_data)
            oauth.refresh_access_token()
            # The library updates its internal token_data upon refresh
            session['yahoo_token_data'] = oauth.token_data
            token_data = oauth.token_data
            print("Successfully refreshed access token and updated session.")
        except Exception as e:
            print(f"Failed to refresh access token: {e}")
            session.clear()
            return None, (jsonify({"error": "Failed to refresh token, please log in again."}), 401)

    # Proceed with a valid token
    oauth = get_oauth_client(token_data)
    gm = game.Game(oauth, 'nhl')
    return gm, None

# --- Route to serve the main HTML file ---
@api_bp.route('/')
def index():
# ... (rest of file remains unchanged)
