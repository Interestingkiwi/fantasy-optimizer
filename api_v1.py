from flask import Blueprint, jsonify, session
# We need to import the DB connection function from your main app.py
# (Assuming it's defined there or in a file app.py imports)
from app import get_db_connection_for_league, requires_auth

# 1. Create the Blueprint
# The first argument 'api_v1' is the internal name.
# The second, __name__, is standard.
# url_prefix='/api/v1' means all routes in this file will
# automatically start with /api/v1
api = Blueprint('api_v1', __name__, url_prefix='/api/v1')


# 2. Define your routes just like in app.py, but use `api.route`
@api.route("/league/<league_id>/players")
@requires_auth # Use your existing auth decorator
def api_get_players_for_league(league_id):
    """
    Returns a JSON list of players for a given league.
    This endpoint is for mobile clients.
    """
    # 1. REUSE your existing logic. No duplication!
    conn, err = get_db_connection_for_league(league_id)
    if err:
        return jsonify({"error": err}), 400

    # 2. Run the same query
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT player_name, team, position FROM players") # Or whatever query you need
        players = cursor.fetchall()
    except Exception as e:
        # Handle query errors
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

    # 3. Convert data to a list of dicts for clean JSON
    player_list = [dict(row) for row in players]

    # 4. Return it as JSON
    return jsonify(player_list)


@api.route("/league/<league_id>/matchups")
@requires_auth
def api_get_matchups(league_id):
    """
    Returns a JSON list of matchups for the league.
    """
    conn, err = get_db_connection_for_league(league_id)
    if err:
        return jsonify({"error": err}), 400

    # ... Your query logic for matchups ...
    matchups = [] # Replace with your real query

    conn.close()

    return jsonify(matchups)


# ... Add all your other mobile API endpoints here ...
