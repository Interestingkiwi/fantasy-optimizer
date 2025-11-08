from gevent import monkey
monkey.patch_all()

"""
Main run app for Fantasystreams.app

Author: Jason Druckenmiller
Date: 10/16/2025
Updated: 10/30/2025
"""

import os
import json
import logging
import sqlite3
from flask import Flask, Response, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from yfpy.query import YahooFantasySportsQuery
import yahoo_fantasy_api as yfa
from yahoo_oauth import OAuth2
from requests_oauthlib import OAuth2Session
import time
import re
import db_builder
import uuid
from datetime import date, timedelta, datetime
import shutil
from collections import defaultdict, Counter
import itertools
import copy
from queue import Queue
import threading


# --- Flask App Configuration ---
# Assume a 'data' directory exists for storing database files
DATA_DIR = '/var/data/dbs'
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

SERVER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server')
TEST_DB_FILENAME = 'yahoo-22705-Albany Hockey Hooligans Test.db'
TEST_DB_PATH = os.path.join(SERVER_DIR, TEST_DB_FILENAME)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-strong-dev-secret-key-for-local-testing")
# Configure root logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_BUILD_QUEUES = {}
DB_QUEUES_LOCK = threading.Lock() # To safely add/remove from the dict

db_build_status = {"running": False, "error": None}
db_build_status_lock = threading.Lock()

# --- Yahoo OAuth2 Settings ---
authorization_base_url = 'https://api.login.yahoo.com/oauth2/request_auth'
token_url = 'https://api.login.yahoo.com/oauth2/get_token'

def model_to_dict(obj):
    """
    Recursively converts yfpy model objects, lists, and bytes into a structure
    that can be easily serialized to JSON.
    """
    if isinstance(obj, list):
        return [model_to_dict(i) for i in obj]

    if isinstance(obj, bytes):
        return obj.decode('utf-8', 'ignore')

    if not hasattr(obj, '__module__') or not obj.__module__.startswith('yfpy.'):
         return obj

    result = {}
    for key in dir(obj):
        if not key.startswith('_') and not callable(getattr(obj, key)):
            value = getattr(obj, key)
            result[key] = model_to_dict(value)
    return result

def get_yfpy_instance():
    """Helper function to get an authenticated yfpy instance."""
    # --- THIS FUNCTION IS NOT THREAD-SAFE (relies on session) ---
    if 'yahoo_token' not in session:
        return None

    if session.get('dev_mode'):
        logging.info("Dev mode: Skipping real yfpy init.")
        pass

    token = session['yahoo_token']
    auth_data = {
        'consumer_key': session.get('consumer_key', 'dev_key'), # Add defaults for dev_mode
        'consumer_secret': session.get('consumer_secret', 'dev_secret'), # Add defaults for dev_mode
        'access_token': token.get('access_token'),
        'refresh_token': token.get('refresh_token'),
        'token_type': token.get('token_type', 'bearer'),
        'token_time': token.get('expires_at', time.time() + token.get('expires_in', 3600)),
        'guid': token.get('xoauth_yahoo_guid')
    }
    try:
        yq = YahooFantasySportsQuery(
            session['league_id'],
            game_code="nhl",
            yahoo_access_token_json=auth_data
        )
        return yq
    except Exception as e:
        logging.error(f"Failed to init yfpy (expected in dev mode): {e}", exc_info=True)
        return None

def get_yfa_lg_instance():
    """Helper function to get an authenticated yfa league instance."""
    # --- THIS FUNCTION IS NOT THREAD-SAFE (relies on session) ---
    if 'yahoo_token' not in session:
        return None

    if session.get('dev_mode'):
        logging.info("Dev mode: Skipping real yfa init.")
        return None

    token = session['yahoo_token']
    consumer_key = session.get('consumer_key')
    consumer_secret = session.get('consumer_secret')
    league_id = session.get('league_id')

    if not all([token, consumer_key, consumer_secret, league_id]):
        logging.error("YFA instance requires token and credentials in session.")
        return None

    creds = {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "access_token": token.get('access_token'),
        "refresh_token": token.get('refresh_token'),
        "token_type": token.get('token_type', 'bearer'),
        "token_time": token.get('expires_at', time.time() + token.get('expires_in', 3600)),
        "xoauth_yahoo_guid": token.get('xoauth_yahoo_guid')
    }

    temp_dir = os.path.join(DATA_DIR, 'temp_creds')
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, f"{uuid.uuid4()}.json")

    try:
        with open(temp_file_path, 'w') as f:
            json.dump(creds, f)

        sc = OAuth2(None, None, from_file=temp_file_path)
        if not sc.token_is_valid():
            logging.info("YFA token expired, refreshing...")
            sc.refresh_access_token()
            # Read the *new* credentials back from the file
            with open(temp_file_path, 'r') as f:
                new_creds = json.load(f)

            # --- CRITICAL: Update the session ---
            session['yahoo_token']['access_token'] = new_creds.get('access_token')
            session['yahoo_token']['refresh_token'] = new_creds.get('refresh_token')
            session['yahoo_token']['expires_at'] = new_creds.get('token_time')
            session.modified = True
            logging.info("Session token updated after YFA refresh.")

        gm = yfa.Game(sc, 'nhl')
        lg = gm.to_league(f"nhl.l.{league_id}")
        return lg
    except Exception as e:
        logging.error(f"Failed to init yfa: {e}", exc_info=True)
        return None
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def get_db_connection_for_league(league_id):
    """Finds and connects to the league's database. Uses a test DB if configured."""
    if session.get('use_test_db'):
        logging.info(f"Using test database: {TEST_DB_PATH}")
        if not os.path.exists(TEST_DB_PATH):
            return None, f"Test database '{TEST_DB_FILENAME}' not found in 'server' directory."
        try:
            writable_test_db_path = os.path.join(DATA_DIR, f"temp_{TEST_DB_FILENAME}")
            shutil.copy2(TEST_DB_PATH, writable_test_db_path)
            conn = sqlite3.connect(writable_test_db_path)
            conn.row_factory = sqlite3.Row
            logging.info(f"Successfully connected to temporary copy of test DB.")
            return conn, None
        except Exception as e:
            logging.error(f"Error connecting to test DB at {TEST_DB_PATH}: {e}")
            return None, "Could not connect to the test database."

    if not league_id:
        return None, "League ID not found in session."

    db_filename = None
    for filename in os.listdir(DATA_DIR):
        if filename.startswith(f"yahoo-{league_id}-") and filename.endswith(".db"):
            db_filename = filename
            break

    if not db_filename:
        return None, "Database file not found. Please initialize it on the 'League Database' page."

    db_path = os.path.join(DATA_DIR, db_filename)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn, None
    except Exception as e:
        logging.error(f"Error connecting to DB at {db_path}: {e}")
        return None, "Could not connect to the database."


def decode_dict_values(data):
    """Recursively decodes byte strings in a dictionary or list of dictionaries."""
    if isinstance(data, list):
        return [decode_dict_values(item) for item in data]
    if isinstance(data, dict):
        return {k: v.decode('utf-8') if isinstance(v, bytes) else v for k, v in data.items()}
    return data


def _get_daily_simulated_roster(base_roster, simulated_moves, day_str):
    """
    Calculates the correct active roster for a given day, applying all
    simulated add/drops that have occurred up to and including that day.
    """
    # 1. Find all players dropped by this date
    # Use int for robust matching
    dropped_player_ids_today = {int(m['dropped_player']['player_id']) for m in simulated_moves if m['date'] <= day_str}

    daily_active_roster = []

    # 2. Add players from the base roster who haven't been dropped
    for p in base_roster:
        if int(p.get('player_id', 0)) not in dropped_player_ids_today:
            daily_active_roster.append(p)

    # 3. Add simulated players who have been added AND have not been subsequently dropped
    for move in simulated_moves:
        added_player = move['added_player']
        add_date = move['date']
        added_player_id = int(added_player.get('player_id', 0))

        is_added = (add_date <= day_str)
        is_not_dropped = (added_player_id not in dropped_player_ids_today)

        if is_added and is_not_dropped:
            daily_active_roster.append(added_player)

    return daily_active_roster


def get_optimal_lineup(players, lineup_settings):
    """
    Calculates the optimal lineup using a three-pass greedy algorithm that prioritizes
    maximizing player starts and then optimizing for the best rank.
    """
    processed_players = []
    for p in players:
        player_copy = p.copy()
        if player_copy.get('total_rank') is None:
            player_copy['total_rank'] = 60
        processed_players.append(player_copy)

    ranked_players = sorted(
        processed_players,
        key=lambda p: p['total_rank']
    )

    lineup = {pos: [] for pos in lineup_settings}
    player_pool = list(ranked_players)

    # --- START MODIFICATION ---
    # Use player_id for tracking. It's guaranteed to exist and be unique.
    assigned_player_ids = set()

    def assign_player(player, pos, current_lineup, assigned_set):
        current_lineup[pos].append(player)
        # Use player_id, which is present on both base and simulated players
        assigned_set.add(player.get('player_id'))
        return True
    # --- END MODIFICATION ---

    # --- Helper to safely get position string ---
    def get_pos_str(p):
        return p.get('eligible_positions') or p.get('positions', '')

    # --- Pass 1: Place players with only one eligible position ---
    single_pos_players = sorted(
        [p for p in player_pool if len(get_pos_str(p).split(',')) == 1],
        key=lambda p: p['total_rank']
    )
    for player in single_pos_players:
        pos = get_pos_str(player).strip()
        if pos in lineup and len(lineup[pos]) < lineup_settings.get(pos, 0):
            # Use the new ID-based set
            assign_player(player, pos, lineup, assigned_player_ids)

    # Filter pool based on player_id
    player_pool = [p for p in player_pool if p.get('player_id') not in assigned_player_ids]

    # --- Pass 2: Place multi-position players using a scarcity-aware algorithm ---
    player_pool.sort(key=lambda p: p['total_rank'])
    for player in player_pool:
        eligible_positions = [pos.strip() for pos in get_pos_str(player).split(',')]
        available_slots_for_player = [
            pos for pos in eligible_positions if pos in lineup and len(lineup[pos]) < lineup_settings.get(pos, 0)
        ]

        if not available_slots_for_player: continue

        slot_scarcity = {}
        for slot in available_slots_for_player:
            scarcity_count = sum(1 for other in player_pool
                                     if other != player and
                                     other.get('player_id') not in assigned_player_ids and
                                     slot in [p.strip() for p in get_pos_str(other).split(',')])
            slot_scarcity[slot] = scarcity_count

        best_pos = min(slot_scarcity, key=slot_scarcity.get)
        # Use the new ID-based set
        assign_player(player, best_pos, lineup, assigned_player_ids)

    # Filter pool based on player_id
    player_pool = [p for p in player_pool if p.get('player_id') not in assigned_player_ids]

    # --- Pass 3: Upgrade Pass ---
    # (This pass is unaffected as it doesn't use the assigned_set)
    for benched_player in player_pool:
        for pos in [p.strip() for p in get_pos_str(benched_player).split(',')]:
            if pos not in lineup: continue

            if not lineup[pos]: continue

            worst_starter_in_pos = max(lineup[pos], key=lambda p: p['total_rank'])

            if benched_player['total_rank'] < worst_starter_in_pos['total_rank']:
                lineup[pos].remove(worst_starter_in_pos)
                lineup[pos].append(benched_player)

                is_re_slotted = False
                for other_pos in [p.strip() for p in get_pos_str(worst_starter_in_pos).split(',')]:
                    if other_pos in lineup and len(lineup[other_pos]) < lineup_settings.get(other_pos, 0):
                        lineup[other_pos].append(worst_starter_in_pos)
                        is_re_slotted = True
                        break
                break

    return lineup


def _get_ranked_roster_for_week(cursor, team_id, week_num):
    """
    Internal helper to fetch a team's full roster for a week and enrich it
    with game schedules and player performance ranks.
    """
    # Get week dates
    cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num,))
    week_dates = cursor.fetchone()
    if not week_dates:
        return [] # Or raise an error
    start_date = datetime.strptime(week_dates['start_date'], '%Y-%m-%d').date()
    end_date = datetime.strptime(week_dates['end_date'], '%Y-%m-%d').date()

    # Get roster and player info, including player_id
    cursor.execute("""
        SELECT
            p.player_id,
            p.player_name,
            p.player_team as team,
            p.player_name_normalized,
            rp.eligible_positions
        FROM rosters_tall r
        JOIN rostered_players rp ON r.player_id = rp.player_id
        JOIN players p ON rp.player_id = p.player_id
        WHERE r.team_id = ?
    """, (team_id,))
    players_raw = cursor.fetchall()
    players = decode_dict_values([dict(row) for row in players_raw])

    # Get scoring categories
    cursor.execute("SELECT category FROM scoring")
    scoring_categories = [row['category'] for row in cursor.fetchall()]
    cat_rank_columns = [f"{cat}_cat_rank" for cat in scoring_categories]

    # Get schedules
    for player in players:
        cursor.execute("SELECT schedule_json FROM team_schedules WHERE team_tricode = ?", (player['team'],))
        schedule_row = cursor.fetchone()
        player['game_dates_this_week'] = []
        if schedule_row and schedule_row['schedule_json']:
            schedule = json.loads(schedule_row['schedule_json'])
            for game_date_str in schedule:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
                if start_date <= game_date <= end_date:
                    player['game_dates_this_week'].append(game_date_str)

    # Filter out IR players
    active_players = [p for p in players if not any(pos.strip().startswith('IR') for pos in p['eligible_positions'].split(','))]
    normalized_names = [p['player_name_normalized'] for p in active_players]

    # Get player stats and calculate total rank
    if normalized_names:
        placeholders = ','.join('?' for _ in normalized_names)
        query = f"""
            SELECT player_name_normalized, {', '.join(cat_rank_columns)}
            FROM joined_player_stats
            WHERE player_name_normalized IN ({placeholders})
        """
        cursor.execute(query, normalized_names)
        player_stats = {row['player_name_normalized']: dict(row) for row in cursor.fetchall()}

        for player in active_players:
            stats = player_stats.get(player['player_name_normalized'])
            if stats:
                total_rank = sum(stats.get(col, 0) or 0 for col in cat_rank_columns)
                player['total_rank'] = round(total_rank, 2)
            else:
                player['total_rank'] = None # Use None for JSON compatibility
            if stats:
                for col in cat_rank_columns:
                    player[col] = stats.get(col) if stats.get(col) is not None else None
    return active_players

def _calculate_unused_spots(days_in_week, active_players, lineup_settings, simulated_moves=None):
    """
    Calculates the unused roster spots for each day of the week and identifies
    potential player movements, applying simulated add/drops if provided.
    """
    if simulated_moves is None:
        simulated_moves = []

    unused_spots_data = {}
    position_order = ['C', 'LW', 'RW', 'D', 'G']

    today = date.today()
    for day_date in days_in_week:
        day_str = day_date.strftime('%Y-%m-%d')
        day_name = day_date.strftime('%a')

        daily_active_roster = _get_daily_simulated_roster(active_players, simulated_moves, day_str)

        players_playing_today = []
        for p in daily_active_roster:
            # Check both 'game_dates_this_week' (for base roster) and 'game_dates_this_week_full' (for added players)
            game_dates = p.get('game_dates_this_week') or p.get('game_dates_this_week_full', [])
            if day_str in game_dates:
                players_playing_today.append(p)

        daily_lineup = get_optimal_lineup(players_playing_today, lineup_settings)

        if day_date < today:
            open_slots = {pos: '-' for pos in position_order}
        else:
            open_slots = {pos: lineup_settings.get(pos, 0) - len(daily_lineup.get(pos, [])) for pos in position_order}

        # Asterisk logic: check if a starter could move to an open slot
        for pos, players in daily_lineup.items():
            if pos not in position_order: continue

            # If this position is full, check if any of its players could move
            if open_slots[pos] == 0:
                for player in players:
                    eligible_positions_str = player.get('eligible_positions') or player.get('positions', '')
                    eligible = [p.strip() for p in eligible_positions_str.split(',')]
                    for other_pos in eligible:
                        current_val = open_slots.get(other_pos)
                        if current_val is not None:
                            # Safely check the value before comparing
                            numeric_val = int(str(current_val).replace('*',''))
                            if numeric_val > 0:
                                open_slots[pos] = f"{open_slots[pos]}*"
                                break
                    if isinstance(open_slots[pos], str):
                        break

        unused_spots_data[day_name] = open_slots

    return unused_spots_data

def _get_ranked_players(cursor, player_ids, cat_rank_columns, week_num):
    """
    Internal helper to fetch player details, ranks, and schedules for a list of player IDs.
    """
    if not player_ids:
        return []

    # Get dates for current and next week
    cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num,))
    week_dates = cursor.fetchone()
    start_date, end_date = None, None
    if week_dates:
        start_date = datetime.strptime(week_dates['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(week_dates['end_date'], '%Y-%m-%d').date()

    cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num + 1,))
    week_dates_next = cursor.fetchone()
    start_date_next, end_date_next = None, None
    if week_dates_next:
        start_date_next = datetime.strptime(week_dates_next['start_date'], '%Y-%m-%d').date()
        end_date_next = datetime.strptime(week_dates_next['end_date'], '%Y-%m-%d').date()

    placeholders = ','.join('?' for _ in player_ids)

    # Construct the full list of columns to select
    columns_to_select = ['player_id', 'player_name', 'player_team', 'positions', 'player_name_normalized'] + cat_rank_columns

    query = f"""
        SELECT {', '.join(columns_to_select)}
        FROM joined_player_stats
        WHERE player_id IN ({placeholders})
    """
    cursor.execute(query, player_ids)
    players_raw = cursor.fetchall()
    players = decode_dict_values([dict(row) for row in players_raw])

    # Calculate total rank and add schedules
    for player in players:
        total_rank = sum(player.get(col, 0) or 0 for col in cat_rank_columns)
        player['total_cat_rank'] = round(total_rank, 2)

        # Get schedules
        player['games_this_week'] = []
        player['games_next_week'] = []
        player['game_dates_this_week_full'] = []
        cursor.execute("SELECT schedule_json FROM team_schedules WHERE team_tricode = ?", (player.get('player_team'),))
        schedule_row = cursor.fetchone()
        if schedule_row and schedule_row['schedule_json']:
            schedule = json.loads(schedule_row['schedule_json'])
            for game_date_str in schedule:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
                if start_date and end_date and start_date <= game_date <= end_date:
                    player['games_this_week'].append(game_date.strftime('%a'))
                    player['game_dates_this_week_full'].append(game_date_str)
                if start_date_next and end_date_next and start_date_next <= game_date <= end_date_next:
                    player['games_next_week'].append(game_date.strftime('%a'))

    return players


@app.route('/healthz')
def health_check():
    return "OK", 200

@app.route('/')
def index():
    if 'yahoo_token' in session:
        return redirect(url_for('home'))
    return render_template('index.html')

@app.route('/home')
def home():
    if 'yahoo_token' not in session:
        return redirect(url_for('index'))
    return render_template('home.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    league_id = data.get('league_id')

    # --- [START] DEV CODE BYPASS ---
    if league_id == '99999':
        session['league_id'] = '22705' # Use the test DB's league ID
        session['use_test_db'] = True
        session['dev_mode'] = True
        session['yahoo_token'] = {
            'access_token': 'dev_token',
            'refresh_token': 'dev_refresh',
            'expires_at': time.time() + 3600
        }
        logging.info("Developer login successful using code 99999. Using test DB.")
        return jsonify({'dev_login': True, 'redirect_url': url_for('home')})
    # --- [END] DEV CODE BYPASS ---

    session['league_id'] = league_id
    session['consumer_key'] = os.environ.get("YAHOO_CONSUMER_KEY")
    session['consumer_secret'] = os.environ.get("YAHOO_CONSUMER_SECRET")

    if not all([session['league_id'], session['consumer_key'], session['consumer_secret']]):
        if not session['consumer_key'] or not session['consumer_secret']:
            logging.error("YAHOO_CONSUMER_KEY or YAHOO_CONSUMER_SECRET not set.")
            return jsonify({"error": "Server is not configured correctly."}), 500
        return jsonify({"error": "League ID is required."}), 400

    redirect_uri = url_for('callback', _external=True, _scheme='https')
    yahoo = OAuth2Session(session['consumer_key'], redirect_uri=redirect_uri)
    authorization_url, state = yahoo.authorization_url(authorization_base_url)
    session['oauth_state'] = state
    return jsonify({'auth_url': authorization_url})

@app.route('/callback')
def callback():
    if 'error' in request.args:
        error_msg = request.args.get('error_description', 'An unknown error occurred.')
        return f'<h1>Error: {error_msg}</h1>', 400

    if request.args.get('state') != session.get('oauth_state'):
        return '<h1>Error: State mismatch.</h1>', 400

    redirect_uri = url_for('callback', _external=True, _scheme='https')
    yahoo = OAuth2Session(session['consumer_key'], state=session.get('oauth_state'), redirect_uri=redirect_uri)

    try:
        token = yahoo.fetch_token(
            token_url,
            client_secret=session['consumer_secret'],
            code=request.args.get('code')
        )
        session['yahoo_token'] = token
    except Exception as e:
        logging.error(f"Error fetching token: {e}", exc_info=True)
        return '<h1>Error: Could not fetch access token.</h1>', 500

    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/query', methods=['POST'])
def handle_query():
    yq = get_yfpy_instance()
    if not yq:
        return jsonify({"error": "Could not connect to Yahoo API. Your session may have expired."}), 401

    query_str = request.get_json().get('query')
    if not query_str:
        return jsonify({"error": "No query provided."}), 400

    logging.info(f"Executing query: {query_str}")
    try:
        result = eval(query_str, {"yq": yq})
        dict_result = model_to_dict(result)
        json_result = json.dumps(dict_result, indent=2)
        return jsonify({"result": json_result})
    except Exception as e:
        logging.error(f"Query error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/yfa_query', methods=['POST'])
def handle_yfa_query():
    lg = get_yfa_lg_instance()
    if not lg:
        return jsonify({"error": "Could not connect to Yahoo API. Your session may have expired."}), 401

    query_str = request.get_json().get('query')
    if not query_str:
        return jsonify({"error": "No query provided."}), 400

    logging.info(f"Executing YFA query: {query_str}")
    try:
        result = eval(query_str, {"lg": lg})
        pretty_result = json.dumps(result, indent=2)
        return jsonify({"result": pretty_result})
    except Exception as e:
        logging.error(f"YFA Query error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/matchup_page_data')
def matchup_page_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)

    if not conn:
        return jsonify({'db_exists': False, 'error': error_msg})

    try:
        cursor = conn.cursor()

        # Fetch weeks
        cursor.execute("SELECT week_num, start_date, end_date FROM weeks ORDER BY week_num")
        weeks = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Fetch teams
        cursor.execute("SELECT team_id, name FROM teams ORDER BY name")
        teams = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Fetch matchups
        cursor.execute("SELECT week, team1, team2 FROM matchups")
        matchups = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Fetch scoring categories, ordered by group (offense, then goalie) then ID
        cursor.execute("SELECT category, stat_id, scoring_group FROM scoring ORDER BY scoring_group DESC, stat_id")
        scoring_categories = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Determine current week
        today = date.today().isoformat()
        cursor.execute("SELECT week_num FROM weeks WHERE start_date <= ? AND end_date >= ?", (today, today))
        current_week_row = cursor.fetchone()
        current_week = current_week_row['week_num'] if current_week_row else (weeks[0]['week_num'] if weeks else 1)

        return jsonify({
            'db_exists': True,
            'weeks': weeks,
            'teams': teams,
            'matchups': matchups,
            'scoring_categories': scoring_categories,
            'current_week': current_week
        })

    except Exception as e:
        logging.error(f"Error fetching matchup page data: {e}", exc_info=True)
        return jsonify({'db_exists': False, 'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/matchup_team_stats', methods=['POST'])
def get_matchup_stats():
    league_id = session.get('league_id')
    data = request.get_json()
    week_num = data.get('week')
    team1_name = data.get('team1_name')
    team2_name = data.get('team2_name')
    simulated_moves = data.get('simulated_moves', [])

    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg}), 404

    cursor = conn.cursor()
    cursor.execute("SELECT category FROM scoring")
    all_scoring_categories = [row['category'] for row in cursor.fetchall()]

    checked_categories = data.get('categories')
    # Handle default case: if no categories are sent, all are checked
    if checked_categories is None:
        checked_categories = all_scoring_categories
    unchecked_categories = [cat for cat in all_scoring_categories if cat not in checked_categories]


    try:
        cursor = conn.cursor()

        # Get team IDs from names
        cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (team1_name,))
        team1_id_row = cursor.fetchone()
        if not team1_id_row: return jsonify({'error': f'Team not found: {team1_name}'}), 404
        team1_id = team1_id_row['team_id']

        cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (team2_name,))
        team2_id_row = cursor.fetchone()
        if not team2_id_row: return jsonify({'error': f'Team not found: {team2_name}'}), 404
        team2_id = team2_id_row['team_id']

        # Get week start/end dates
        cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num,))
        week_dates = cursor.fetchone()
        if not week_dates: return jsonify({'error': f'Week not found: {week_num}'}), 404
        start_date_str = week_dates['start_date']
        end_date_str = week_dates['end_date']
        start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        days_in_week = [(start_date_obj + timedelta(days=i)) for i in range((end_date_obj - start_date_obj).days + 1)]


        # Get official scoring categories
        cursor.execute("SELECT category FROM scoring")
        scoring_categories = [row['category'] for row in cursor.fetchall()]

        # Ensure all necessary sub-categories for calculations are included
        required_cats = {'SV', 'SA', 'GA', 'TOI/G'}
        all_categories_to_fetch = list(set(scoring_categories) | required_cats)

        # Categories to fetch from joined_player_stats (projections).
        projection_cats = list(set(all_categories_to_fetch) - {'TOI/G', 'SVpct'})

        cursor.execute("SELECT position, position_count FROM lineup_settings WHERE position NOT IN ('BN', 'IR', 'IR+')")
        lineup_settings = {row['position']: row['position_count'] for row in cursor.fetchall()}


        # --- Calculate Live Stats ---
        cursor.execute("""
            SELECT team_id, category, SUM(stat_value) as total
            FROM daily_player_stats
            WHERE date_ >= ? AND date_ <= ? AND (team_id = ? OR team_id = ?)
            GROUP BY team_id, category
        """, (start_date_str, end_date_str, team1_id, team2_id))

        live_stats_raw = cursor.fetchall()
        live_stats_decoded = decode_dict_values([dict(row) for row in live_stats_raw])

        stats = {
            'team1': {'live': {cat: 0 for cat in all_categories_to_fetch}, 'row': {}},
            'team2': {'live': {cat: 0 for cat in all_categories_to_fetch}, 'row': {}},
            'game_counts': {
                'team1_total': 0,
                'team2_total': 0,
                'team1_remaining': 0,
                'team2_remaining': 0
            }
        }

        for row in live_stats_decoded:
          team_key = 'team1' if str(row['team_id']) == str(team1_id) else 'team2'
          if row['category'] in all_categories_to_fetch:
              stats[team_key]['live'][row['category']] = row.get('total', 0)

      # --- [START] NEW BLOCK: Calculate Live Derived Stats & Apply SHO Fix ---
        for team_key in ['team1', 'team2']:
          live_stats = stats[team_key]['live']

          # Apply TOI/G fix for shutouts
          # This assumes daily_player_stats stores 0 TOI/G for shutouts,
          # but does store 1.0 for the SHO category itself.
          if 'SHO' in live_stats and live_stats['SHO'] > 0:
              # live_stats['SHO'] is the SUM of shutouts (e.g., 2.0)
              # We add 60 minutes to TOI/G for *each* shutout.
              live_stats['TOI/G'] += (live_stats['SHO'] * 60)

          # Re-calculate live GAA and SVpct based on summed components
          # The values from the DB are just sums of daily GAA/SVpct, which is incorrect.
          if 'GAA' in live_stats:
              live_stats['GAA'] = (live_stats.get('GA', 0) * 60) / live_stats['TOI/G'] if live_stats.get('TOI/G', 0) > 0 else 0

          if 'SVpct' in live_stats:
              live_stats['SVpct'] = live_stats.get('SV', 0) / live_stats['SA'] if live_stats.get('SA', 0) > 0 else 0
              # --- [END] NEW BLOCK ---

        # --- Calculate ROW (Rest of Week) Stats ---
        stats['team1']['row'] = copy.deepcopy(stats['team1']['live'])
        stats['team2']['row'] = copy.deepcopy(stats['team2']['live'])

        team1_ranked_roster = _get_ranked_roster_for_week(cursor, team1_id, week_num)
        team2_ranked_roster = _get_ranked_roster_for_week(cursor, team2_id, week_num)

        rosters_to_update = [team1_ranked_roster, team2_ranked_roster]

        today = date.today()
        projection_start_date = max(today, start_date_obj)

        current_date = projection_start_date
        while current_date <= end_date_obj:
            current_date_str = current_date.strftime('%Y-%m-%d')

            # --- NEW: Build Team 1's daily roster ---
            t1_daily_roster = _get_daily_simulated_roster(team1_ranked_roster, simulated_moves, current_date_str)
            # Use int for robust matching

            t1_players_today = []
            for p in t1_daily_roster:
                game_dates = p.get('game_dates_this_week') or p.get('game_dates_this_week_full', [])
                if current_date_str in game_dates:
                    t1_players_today.append(p)
            team2_players_today = [p for p in team2_ranked_roster if current_date_str in p.get('game_dates_this_week', [])]

            team1_lineup = get_optimal_lineup(t1_players_today, lineup_settings)
            team2_lineup = get_optimal_lineup(team2_players_today, lineup_settings)

            team1_starters = [player for pos_players in team1_lineup.values() for player in pos_players]
            team2_starters = [player for pos_players in team2_lineup.values() for player in pos_players]

            stats['game_counts']['team1_remaining'] += len(team1_starters)
            stats['game_counts']['team2_remaining'] += len(team2_starters)

            all_starter_ids_today = [p['player_id'] for p in team1_starters + team2_starters]

            if all_starter_ids_today:
                placeholders = ','.join('?' for _ in all_starter_ids_today)
                query = f"SELECT player_id, {', '.join(projection_cats)} FROM joined_player_stats WHERE player_id IN ({placeholders})"
                cursor.execute(query, tuple(all_starter_ids_today))
                player_avg_stats = {row['player_id']: dict(row) for row in cursor.fetchall()}

                for starter in team1_starters:
                    if starter['player_id'] in player_avg_stats:
                        player_proj = player_avg_stats[starter['player_id']]
                        for category in projection_cats:
                            stat_val = player_proj.get(category) or 0
                            stats['team1']['row'][category] += stat_val

                        # Safely get position string from either key
                        pos_str = starter.get('eligible_positions') or starter.get('positions', '')
                        if 'G' in pos_str.split(','):
                            stats['team1']['row']['TOI/G'] += 60

                for starter in team2_starters:
                    if starter['player_id'] in player_avg_stats:
                        player_proj = player_avg_stats[starter['player_id']]
                        for category in projection_cats:
                            stat_val = player_proj.get(category) or 0
                            stats['team2']['row'][category] += stat_val

                        # Safely get position string from either key
                        pos_str = starter.get('eligible_positions') or starter.get('positions', '')
                        if 'G' in pos_str.split(','):
                            stats['team2']['row']['TOI/G'] += 60

            current_date += timedelta(days=1)

        # --- Final ROW Calculations and Rounding ---
        for team_key in ['team1', 'team2']:
            row_stats = stats[team_key]['row']

            gaa = (row_stats.get('GA', 0) * 60) / row_stats['TOI/G'] if row_stats.get('TOI/G', 0) > 0 else 0
            sv_pct = row_stats.get('SV', 0) / row_stats['SA'] if row_stats.get('SA', 0) > 0 else 0

            # Apply rounding to all stats
            for cat, value in row_stats.items():
                if cat == 'GAA':
                    row_stats[cat] = round(gaa, 2)
                elif cat == 'SVpct':
                    row_stats[cat] = round(sv_pct, 3)
                elif isinstance(value, (int, float)) and cat not in ['GAA', 'SVpct']:
                    row_stats[cat] = round(value, 1)
        for day_date in days_in_week:
            day_str = day_date.strftime('%Y-%m-%d')

            # --- NEW: Build Team 1's daily roster (repeat logic) ---
            t1_daily_roster = _get_daily_simulated_roster(team1_ranked_roster, simulated_moves, day_str)

            t1_players_today = []
            for p in t1_daily_roster:
                game_dates = p.get('game_dates_this_week') or p.get('game_dates_this_week_full', [])
                if day_str in game_dates:
                    t1_players_today.append(p)
            # --- END NEW ---

            team2_players_today = [p for p in team2_ranked_roster if day_str in p.get('game_dates_this_week', [])]

            team1_lineup = get_optimal_lineup(t1_players_today, lineup_settings)
            team2_lineup = get_optimal_lineup(team2_players_today, lineup_settings)

            team1_starters = [player for pos_players in team1_lineup.values() for player in pos_players]
            team2_starters = [player for pos_players in team2_lineup.values() for player in pos_players]

            stats['game_counts']['team1_total'] += len(team1_starters)
            stats['game_counts']['team2_total'] += len(team2_starters)
        # --- Calculate Unused Roster Spots for Team 1 ---
        stats['team1_unused_spots'] = _calculate_unused_spots(days_in_week, team1_ranked_roster, lineup_settings, simulated_moves)


        return jsonify(stats)

    except Exception as e:
        logging.error(f"Error fetching matchup stats: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/lineup_page_data')
def lineup_page_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)

    if not conn:
        return jsonify({'db_exists': False, 'error': error_msg})

    try:
        cursor = conn.cursor()

        # Fetch weeks
        cursor.execute("SELECT week_num, start_date, end_date FROM weeks ORDER BY week_num")
        weeks = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Fetch teams
        cursor.execute("SELECT team_id, name FROM teams ORDER BY name")
        teams = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Determine current week
        today = date.today().isoformat()
        cursor.execute("SELECT week_num FROM weeks WHERE start_date <= ? AND end_date >= ?", (today, today))
        current_week_row = cursor.fetchone()
        current_week = current_week_row['week_num'] if current_week_row else (weeks[0]['week_num'] if weeks else 1)

        return jsonify({
            'db_exists': True,
            'weeks': weeks,
            'teams': teams,
            'current_week': current_week
        })

    except Exception as e:
        logging.error(f"Error fetching lineup page data: {e}", exc_info=True)
        return jsonify({'db_exists': False, 'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/season_history_page_data')
def season_history_page_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)

    if not conn:
        return jsonify({'db_exists': False, 'error': error_msg})

    try:
        cursor = conn.cursor()

        # Fetch weeks
        cursor.execute("SELECT week_num, start_date, end_date FROM weeks ORDER BY week_num")
        weeks = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Fetch teams
        cursor.execute("SELECT team_id, name FROM teams ORDER BY name")
        teams = decode_dict_values([dict(row) for row in cursor.fetchall()])

        # Determine current week
        today = date.today().isoformat()
        cursor.execute("SELECT week_num FROM weeks WHERE start_date <= ? AND end_date >= ?", (today, today))
        current_week_row = cursor.fetchone()
        current_week = current_week_row['week_num'] if current_week_row else (weeks[0]['week_num'] if weeks else 1)

        return jsonify({
            'db_exists': True,
            'weeks': weeks,
            'teams': teams,
            'current_week': current_week
        })

    except Exception as e:
        logging.error(f"Error fetching season history page data: {e}", exc_info=True)
        return jsonify({'db_exists': False, 'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


def _get_live_matchup_stats(cursor, team1_id, team2_id, start_date_str, end_date_str):
    """
    Fetches only the 'live' stats for two teams for a given date range.
    """

    # Get official scoring categories in display order
    cursor.execute("SELECT category FROM scoring ORDER BY scoring_group DESC, stat_id")
    scoring_categories = [row['category'] for row in cursor.fetchall()]

    # Ensure all necessary sub-categories for calculations are included
    required_cats = {'SV', 'SA', 'GA', 'TOI/G'}
    all_categories_to_fetch = list(set(scoring_categories) | required_cats)

    # --- Calculate Live Stats ---
    cursor.execute("""
        SELECT team_id, category, SUM(stat_value) as total
        FROM daily_player_stats
        WHERE date_ >= ? AND date_ <= ? AND (team_id = ? OR team_id = ?)
        GROUP BY team_id, category
    """, (start_date_str, end_date_str, team1_id, team2_id))

    live_stats_raw = cursor.fetchall()
    live_stats_decoded = decode_dict_values([dict(row) for row in live_stats_raw])

    stats = {
        'team1': {'live': {cat: 0 for cat in all_categories_to_fetch}},
        'team2': {'live': {cat: 0 for cat in all_categories_to_fetch}}
    }

    for row in live_stats_decoded:
        team_key = 'team1' if str(row['team_id']) == str(team1_id) else 'team2'
        if row['category'] in all_categories_to_fetch:
            stats[team_key]['live'][row['category']] = row.get('total', 0)

    # --- Calculate Live Derived Stats & Apply SHO Fix ---
    for team_key in ['team1', 'team2']:
        live_stats = stats[team_key]['live']

        if 'SHO' in live_stats and live_stats['SHO'] > 0:
            live_stats['TOI/G'] += (live_stats['SHO'] * 60)

        if 'GAA' in live_stats:
            live_stats['GAA'] = (live_stats.get('GA', 0) * 60) / live_stats['TOI/G'] if live_stats.get('TOI/G', 0) > 0 else 0

        if 'SVpct' in live_stats:
            live_stats['SVpct'] = live_stats.get('SV', 0) / live_stats['SA'] if live_stats.get('SA', 0) > 0 else 0

    # Rounding for display
    for team_key in ['team1', 'team2']:
        live_stats = stats[team_key]['live']
        for cat, value in live_stats.items():
            if cat == 'GAA':
                live_stats[cat] = round(value, 2)
            elif cat == 'SVpct':
                live_stats[cat] = round(value, 3)
            elif isinstance(value, (int, float)):
                live_stats[cat] = round(value, 1)

    return {
        'your_team_stats': stats['team1']['live'],
        'opponent_team_stats': stats['team2']['live'],
        'scoring_categories': scoring_categories # Return the ordered list
    }


def _calculate_bench_optimization(cursor, team_id, week_num, start_date, end_date, matchup_data):
    """
    Performs a daily greedy simulation to find the "optimal" lineup
    by swapping bench players for the weakest starters.
    """
    try:
        logging.info("--- Starting Bench Optimization ---")

        # 1. Get data needed for simulation

        # Get lineup settings
        cursor.execute("SELECT position FROM lineup_settings WHERE position NOT IN ('BN', 'IR', 'IR+')")
        starter_positions = {row['position'] for row in cursor.fetchall()} # e.g., {'C', 'LW', 'RW', 'D', 'G'}
        logging.info(f"Starter positions: {starter_positions}")

        # Create position mapping
        pos_map = {
            'c': 'C', 'l': 'LW', 'r': 'RW', 'd': 'D', 'g': 'G',
            'b': 'BN', 'i': 'IR'
        }

        # Get scoring categories
        scoring_categories = matchup_data['scoring_categories']
        reverse_cats = {'GA', 'GAA'}

        # Get opponent stats
        opponent_stats = matchup_data['opponent_team_stats']

        # Create a deep copy of our stats to modify
        optimized_stats = copy.deepcopy(matchup_data['your_team_stats'])

        # Query BOTH tables
        logging.info("Querying for ALL player stats (starters and bench)...")

        cursor.execute("""
            SELECT
                d.date_, d.player_id, d.lineup_pos, d.category, d.stat_value,
                p.player_name, p.positions
            FROM daily_player_stats d
            JOIN players p ON d.player_id = p.player_id
            WHERE d.team_id = ? AND d.date_ >= ? AND d.date_ <= ?

            UNION ALL

            SELECT
                b.date_, b.player_id, b.lineup_pos, b.category, b.stat_value,
                p.player_name, p.positions
            FROM daily_bench_stats b
            JOIN players p ON b.player_id = p.player_id
            WHERE b.team_id = ? AND b.date_ >= ? AND b.date_ <= ?

            ORDER BY 1, 2
        """, (team_id, start_date, end_date, team_id, start_date, end_date))

        all_stats_raw = decode_dict_values([dict(row) for row in cursor.fetchall()])

        if not all_stats_raw:
            logging.warning("No daily_player_stats or daily_bench_stats found for optimization.")
            return matchup_data, []

        logging.info(f"Found {len(all_stats_raw)} total stat rows for simulation.")

        # 2. Pivot data by day and player
        daily_player_performances = defaultdict(lambda: defaultdict(lambda: {
            'stats': defaultdict(float), 'player_id': None, 'player_name': None,
            'lineup_pos': None, 'eligible_positions': []
        }))

        for row in all_stats_raw:
            day = row['date_']
            pid = row['player_id']
            player = daily_player_performances[day][pid]

            player['stats'][row['category']] = row['stat_value']
            player['player_id'] = pid
            player['player_name'] = row['player_name']
            player['lineup_pos'] = pos_map.get(row['lineup_pos'], row['lineup_pos']) # Normalize pos
            player['eligible_positions'] = row['positions'].split(',')

        # 3. Start the simulation
        swaps_log = []

        week_dates = sorted(daily_player_performances.keys())
        logging.info(f"Simulating days: {week_dates}")

        for day in week_dates:
            logging.info(f"--- Simulating Day: {day} ---")
            performances = daily_player_performances[day]

            starters = [p for p in performances.values() if p['lineup_pos'] in starter_positions]
            bench = [p for p in performances.values() if p['lineup_pos'] == 'BN' and sum(p['stats'].values()) > 0]

            logging.info(f"Found {len(starters)} starters and {len(bench)} scoring bench players.")

            if not bench or not starters:
                logging.info("No bench players or starters, skipping day.")
                continue

            replaced_starters_today = set() # Prevent double-swapping

            # Iterate through each bench player
            for bench_player in bench:
                logging.info(f"Evaluating bench player: {bench_player['player_name']} (Eligible: {bench_player['eligible_positions']})")
                best_swap = {
                    'starter_to_replace': None,
                    'net_gain_score': 0
                }

                bench_stats = bench_player['stats']

                # Find all starters this player is eligible to replace
                for starter in starters:
                    if starter['player_id'] in replaced_starters_today:
                        continue

                    if starter['lineup_pos'] not in bench_player['eligible_positions']:
                        logging.debug(f"  -> Skipping {starter['player_name']}: Bench player not eligible for {starter['lineup_pos']}")
                        continue

                    # This is a valid swap. Let's score it.
                    starter_stats = starter['stats']
                    current_swap_score = 0

                    for cat in scoring_categories:
                        stat_diff = bench_stats.get(cat, 0) - starter_stats.get(cat, 0)
                        if stat_diff == 0:
                            continue

                        my_current_total = optimized_stats[cat]
                        opp_total = opponent_stats.get(cat, 0)
                        my_new_total = my_current_total + stat_diff

                        is_reverse = cat in reverse_cats

                        current_points = 0
                        if (my_current_total > opp_total and not is_reverse) or (my_current_total < opp_total and is_reverse):
                            current_points = 2 # Current Win
                        elif my_current_total == opp_total:
                            current_points = 1 # Current Tie

                        new_points = 0
                        if (my_new_total > opp_total and not is_reverse) or (my_new_total < opp_total and is_reverse):
                            new_points = 2 # New Win
                        elif my_new_total == opp_total:
                            new_points = 1 # New Tie

                        current_swap_score += (new_points - current_points)

                    logging.info(f"  -> vs {starter['player_name']} ({starter['lineup_pos']}): net score = {current_swap_score}")

                    if current_swap_score > best_swap['net_gain_score']:
                        best_swap['net_gain_score'] = current_swap_score
                        best_swap['starter_to_replace'] = starter

                # After checking all starters, make the best swap if it's beneficial
                if best_swap['net_gain_score'] > 0 and best_swap['starter_to_replace']:
                    starter_to_replace = best_swap['starter_to_replace']

                    logging.info(f"  ==> SWAP FOUND: {bench_player['player_name']} for {starter_to_replace['player_name']} (Score: {best_swap['net_gain_score']})")

                    # --- START MODIFICATION ---
                    # Calculate and store the stat diffs for this specific swap
                    stat_diffs = {}
                    starter_stats = starter_to_replace['stats']
                    for cat in scoring_categories:
                        stat_diff = bench_stats.get(cat, 0) - starter_stats.get(cat, 0)
                        if stat_diff != 0:
                            stat_diffs[cat] = stat_diff
                    # --- END MODIFICATION ---

                    # 1. Log the swap
                    swaps_log.append({
                        'date': day,
                        'position': starter_to_replace['lineup_pos'],
                        'bench_player': bench_player['player_name'],
                        'replaced_player': starter_to_replace['player_name'],
                        'stat_diffs': stat_diffs  # <-- ADDED
                    })

                    # 2. Mark starter as "used" for this day
                    replaced_starters_today.add(starter_to_replace['player_id'])

                    # 3. Apply the stat changes to our optimized totals
                    for cat, diff in stat_diffs.items():
                        logging.info(f"    Applying {cat}: {optimized_stats[cat]:.1f} + ({diff:.1f}) = {optimized_stats[cat] + diff:.1f}")
                        optimized_stats[cat] += diff
                else:
                    logging.info(f"  -> No beneficial swap found for {bench_player['player_name']}.")


        # 4. Create the final optimized matchup data object
        # Recalculate derived stats (GAA, SVpct)
        if 'GAA' in optimized_stats:
            optimized_stats['GAA'] = (optimized_stats.get('GA', 0) * 60) / optimized_stats['TOI/G'] if optimized_stats.get('TOI/G', 0) > 0 else 0
        if 'SVpct' in optimized_stats:
            optimized_stats['SVpct'] = optimized_stats.get('SV', 0) / optimized_stats['SA'] if optimized_stats.get('SA', 0) > 0 else 0

        # Rounding
        for cat, value in optimized_stats.items():
            if cat == 'GAA':
                optimized_stats[cat] = round(value, 2)
            elif cat == 'SVpct':
                optimized_stats[cat] = round(value, 3)
            elif isinstance(value, (int, float)):
                optimized_stats[cat] = round(value, 1)

        optimized_matchup_data = copy.deepcopy(matchup_data)
        optimized_matchup_data['your_team_stats'] = optimized_stats

        logging.info(f"--- Bench Optimization Complete. Found {len(swaps_log)} swaps. ---")
        return optimized_matchup_data, swaps_log

    except Exception as e:
        logging.error(f"Error in _calculate_bench_optimization: {e}", exc_info=True)
        # Return the original data if simulation fails
        return matchup_data, []

@app.route('/api/history/bench_points', methods=['POST'])
def get_bench_points_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg}), 404

    try:
        cursor = conn.cursor()
        data = request.get_json()
        team_name = data.get('team_name')
        week = data.get('week')

        logging.info("--- History Report ---")
        logging.info(f"Selected team: {team_name}, week: '{week}'")

        # 1. Get team_id
        cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (team_name,))
        team_id_row = cursor.fetchone()
        if not team_id_row:
            return jsonify({'error': f'Team not found: {team_name}'}), 404
        team_id = team_id_row['team_id']
        logging.info(f"Found team_id: {team_id}")

        # 2. Get Dates & Matchup Data
        start_date, end_date = None, None
        matchup_data = None
        optimized_matchup_data = None
        swaps_log = []
        week_num_int = None # Initialize

        if week != 'all':
            try:
                week_num_int = int(week)
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid week format.'}), 400

            logging.info(f"Querying 'weeks' table for week_num = {week_num_int}")
            cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num_int,))
            week_dates = cursor.fetchone()

            if week_dates:
                start_date = week_dates['start_date']
                end_date = week_dates['end_date']
                logging.info(f"Found week dates: {start_date} to {end_date}")

            if start_date and end_date:
                logging.info(f"Querying 'matchups' for week = {week_num_int}, team = '{team_name}'")
                cursor.execute(
                    "SELECT team1, team2 FROM matchups WHERE week = ? AND (CAST(team1 AS TEXT) = ? OR CAST(team2 AS TEXT) = ?)",
                    (week_num_int, team_name, team_name)
                )
                matchup_row = cursor.fetchone()

                if matchup_row:
                    matchup_row_decoded = decode_dict_values(dict(matchup_row))
                    opponent_name = matchup_row_decoded['team2'] if matchup_row_decoded['team1'] == team_name else matchup_row_decoded['team1']
                    logging.info(f"Found opponent_name: {opponent_name}")

                    cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (opponent_name,))
                    opponent_id_row = cursor.fetchone()

                    if opponent_id_row:
                        opponent_id = opponent_id_row['team_id']
                        logging.info(f"Found opponent_id: {opponent_id}")

                        # Get original matchup results
                        matchup_data = _get_live_matchup_stats(cursor, team_id, opponent_id, start_date, end_date)
                        matchup_data['opponent_name'] = opponent_name
                        logging.info("Successfully generated base matchup_data.")

                        # --- RUN OPTIMIZATION ---
                        optimized_matchup_data, swaps_log = _calculate_bench_optimization(
                            cursor, team_id, week_num_int, start_date, end_date, matchup_data
                        )
                        # --- END OPTIMIZATION ---
                    else:
                        logging.warning(f"Could not find team_id for opponent_name = {opponent_name}")
                else:
                    logging.warning(f"Query 2 FAILED: Could not find matchup_row for week = {week_num_int}")
            else:
                logging.warning("Query 1 FAILED: Could not find week_dates.")
        else:
            logging.info("Week is 'all', skipping matchup data fetch.")

        # --- 3. GET BENCH STATS (for the table) ---
        # This logic is now separate from the optimization

        logging.info("Proceeding to fetch bench stats for table display...")
        cursor.execute("SELECT category FROM scoring ORDER BY stat_id")
        all_cats_raw = cursor.fetchall()
        known_goalie_stats = {'W', 'L', 'GA', 'SV', 'SA', 'SHO', 'TOI/G', 'GAA', 'SVpct'}
        all_categories = [row['category'] for row in all_cats_raw]
        goalie_categories = [cat for cat in all_categories if cat in known_goalie_stats]
        skater_categories = [cat for cat in all_categories if cat not in known_goalie_stats]

        sql_params = [team_id]
        sql_query = """
            SELECT d.date_, d.player_id, p.player_name, p.positions, d.category, d.stat_value
            FROM daily_bench_stats d
            JOIN players p ON d.player_id = p.player_id
            WHERE d.team_id = ?
        """

        if start_date and end_date: # Only show week-specific bench stats
            sql_query += " AND d.date_ >= ? AND d.date_ <= ?"
            sql_params.extend([start_date, end_date])
        elif week != 'all': # Week was selected but no dates found (error)
             sql_query += " AND 1=0" # Force no results
        else: # 'all' weeks selected
             pass # Get all bench stats for the season

        sql_query += " ORDER BY d.date_, p.player_name"
        cursor.execute(sql_query, tuple(sql_params))
        raw_stats = decode_dict_values([dict(row) for row in cursor.fetchall()])
        logging.info(f"Found {len(raw_stats)} raw bench stat rows for table.")

        # Pivot the data
        daily_player_stats = defaultdict(lambda: defaultdict(float))
        player_positions = {}
        for row in raw_stats:
            key = (row['date_'], row['player_id'], row['player_name'])
            daily_player_stats[key][row['category']] = row['stat_value']
            player_positions[key] = row['positions']

        skater_rows, goalie_rows = [], []
        for (date, player_id, player_name), stats in daily_player_stats.items():
            if sum(stats.values()) == 0:
                continue
            key = (date, player_id, player_name)
            positions_str = player_positions.get(key, '')
            base_row = {'Date': date, 'Player': player_name, 'Positions': positions_str}
            is_goalie = 'G' in positions_str.split(',')
            if is_goalie:
                for cat in goalie_categories:
                    base_row[cat] = stats.get(cat, 0)
                goalie_rows.append(base_row)
            else:
                for cat in skater_categories:
                    base_row[cat] = stats.get(cat, 0)
                skater_rows.append(base_row)

        logging.info(f"Processed into {len(skater_rows)} skater and {len(goalie_rows)} goalie rows.")

        # 4. Return all data
        logging.info("--- History Report End ---")
        return jsonify({
            'skater_data': skater_rows,
            'skater_headers': skater_categories,
            'goalie_data': goalie_rows,
            'goalie_headers': goalie_categories,
            'matchup_data': matchup_data, # Original
            'optimized_matchup_data': optimized_matchup_data, # New
            'swaps_log': swaps_log # New
        })

    except Exception as e:
        logging.error(f"Error fetching bench points data: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/history/transaction_history', methods=['POST'])
def get_transaction_history_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg}), 404

    try:
        cursor = conn.cursor()
        data = request.get_json()
        team_name = data.get('team_name')
        week = data.get('week')
        # NEW: Get the view mode, default to 'team'
        view_mode = data.get('view_mode', 'team')

        logging.info(f"--- Transaction Success Report ---")
        logging.info(f"Selected team: {team_name}, week: '{week}', view_mode: '{view_mode}'")

        # --- MODIFIED: Get scoring group to differentiate skaters/goalies ---
        cursor.execute("SELECT category, scoring_group FROM scoring ORDER BY scoring_group DESC, stat_id")
        all_categories_raw = cursor.fetchall()
        skater_categories = [row['category'] for row in all_categories_raw if row['scoring_group'] == 'offense']
        goalie_categories = [row['category'] for row in all_categories_raw if row['scoring_group'] == 'goaltending']
        # --- END MODIFIED ---

        start_date, end_date = None, None
        is_weekly_view = False

        if week != 'all':
            is_weekly_view = True
            try:
                week_num_int = int(week)
                cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num_int,))
                week_dates = cursor.fetchone()
                if week_dates:
                    start_date = week_dates['start_date']
                    end_date = week_dates['end_date']
                    logging.info(f"Found week dates: {start_date} to {end_date}")
                else:
                    logging.warning(f"Could not find week_num = {week_num_int}")
                    is_weekly_view = False
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid week format.'}), 400

        # --- NEW: Logic split for Team vs League View ---

        if view_mode == 'team':
            # --- This is the existing logic for Team View ---
            # --- MODIFIED: Create separate lists for skaters and goalies ---
            added_skater_stats = []
            added_goalie_stats = []
            # --- END MODIFIED ---

            def fetch_transactions(move_type):
                sql_params = [team_name, move_type]
                sql_query = """
                    SELECT transaction_date, player_name, player_id
                    FROM transactions
                    WHERE CAST(fantasy_team AS TEXT) = ? AND move_type = ?
                """
                if start_date and end_date:
                    sql_query += " AND transaction_date >= ? AND transaction_date <= ?"
                    sql_params.extend([start_date, end_date])

                sql_query += " ORDER BY transaction_date, player_name"
                cursor.execute(sql_query, tuple(sql_params))
                return decode_dict_values([dict(row) for row in cursor.fetchall()])

            add_rows = fetch_transactions('add')
            drop_rows = fetch_transactions('drop')
            logging.info(f"Found {len(add_rows)} adds and {len(drop_rows)} drops for team '{team_name}'.")

            if is_weekly_view and add_rows:
                logging.info("Fetching weekly stats for added players (Team View)...")
                for player in add_rows:
                    player_stats = {'Player': player['player_name'], 'GP': 0}
                    player_id_str = str(player['player_id'])

                    # --- REVERTED: Query 1: Check for 'g' in daily_player_stats ---
                    cursor.execute("""
                        SELECT 1
                        FROM daily_player_stats
                        WHERE CAST(player_id AS TEXT) = ?
                          AND date_ >= ? AND date_ <= ?
                          AND lineup_pos = 'g'
                        LIMIT 1
                    """, (player_id_str, start_date, end_date))
                    is_goalie = cursor.fetchone() is not None
                    # --- END REVERTED ---

                    # --- Query 2: Get aggregated stats (simplified) ---
                    cursor.execute("""
                        SELECT category, SUM(stat_value) as total
                        FROM daily_player_stats
                        WHERE CAST(player_id AS TEXT) = ?
                          AND date_ >= ? AND date_ <= ?
                        GROUP BY category
                    """, (player_id_str, start_date, end_date))

                    stats_raw = cursor.fetchall()
                    player_stat_map = {row['category']: row['total'] for row in stats_raw}

                    # --- MODIFIED: Query 3: Get Games Played with non-zero stats ---
                    cursor.execute("""
                        SELECT COUNT(T.date_) as games_played
                        FROM (
                            SELECT date_, SUM(stat_value) as total_stats
                            FROM daily_player_stats
                            WHERE CAST(player_id AS TEXT) = ?
                              AND date_ >= ? AND date_ <= ?
                            GROUP BY date_
                            HAVING total_stats > 0
                        ) T
                    """, (player_id_str, start_date, end_date))

                    gp_row = cursor.fetchone()
                    if gp_row:
                        player_stats['GP'] = gp_row['games_played']
                    # --- END MODIFIED ---

                    # --- MODIFIED: Populate based on position and fill 0s ---
                    if is_goalie:
                        # --- NEW: Calculate SVpct and GAA ---
                        sv = player_stat_map.get('SV', 0)
                        sa = player_stat_map.get('SA', 0)
                        ga = player_stat_map.get('GA', 0)
                        toi = player_stat_map.get('TOI/G', 0) # Assumes 'TOI/G' is the time-on-ice stat

                        if 'SVpct' in goalie_categories:
                            player_stat_map['SVpct'] = (sv / sa) if sa > 0 else 0.0

                        if 'GAA' in goalie_categories:
                            player_stat_map['GAA'] = ((float(ga) * 60) / toi) if toi > 0 else 0.0
                        # --- END NEW ---

                        for cat in goalie_categories:
                            player_stats[cat] = player_stat_map.get(cat, 0)

                        # --- NEW: Add sub-stats for JS to use ---
                        player_stats['SV'] = sv
                        player_stats['SA'] = sa
                        player_stats['GA'] = ga
                        player_stats['TOI/G'] = toi
                        # --- END NEW ---

                        added_goalie_stats.append(player_stats)
                    else:
                        for cat in skater_categories:
                            player_stats[cat] = player_stat_map.get(cat, 0)
                        added_skater_stats.append(player_stats)
                    # --- END MODIFIED ---

            return jsonify({
                'view_mode': 'team',
                'adds': add_rows,
                'drops': drop_rows,
                # --- MODIFIED: Send separate lists and headers ---
                'added_skater_stats': added_skater_stats,
                'added_goalie_stats': added_goalie_stats,
                'skater_stat_headers': skater_categories,
                'goalie_stat_headers': goalie_categories,
                # --- END MODIFIED ---
                'is_weekly_view': is_weekly_view
            })

        elif view_mode == 'league':
            # --- This is the new logic for League View ---
            if not is_weekly_view:
                return jsonify({'error': 'League View requires a specific week to be selected.'}), 400

            # Get team name -> team_id map
            cursor.execute("SELECT team_id, name FROM teams")

            # --- MODIFIED: Decode bytes to string, then strip whitespace ---
            teams_map = {row['name'].decode('utf-8').strip(): row['team_id'] for row in cursor.fetchall()}

            # --- NEW DEBUGGING ---
            logging.info(f"Team map keys: {list(teams_map.keys())}")
            # --- END DEBUGGING ---

            # Get all 'add' transactions for the week
            cursor.execute("""
                SELECT transaction_date, player_name, player_id, fantasy_team
                FROM transactions
                WHERE move_type = 'add'
                  AND transaction_date >= ? AND transaction_date <= ?
                ORDER BY fantasy_team, transaction_date, player_name
            """, (start_date, end_date))

            all_adds = decode_dict_values([dict(row) for row in cursor.fetchall()])
            logging.info(f"Found {len(all_adds)} total adds for the league in week {week}.")

            # --- MODIFIED: league_data to hold skater/goalie lists ---
            league_data = defaultdict(lambda: {'skaters': [], 'goalies': []})
            # --- END MODIFIED ---

            for player in all_adds:
                # --- MODIFIED: Strip whitespace from transaction team name before lookup ---
                team_name = player['fantasy_team'].strip()
                team_id = teams_map.get(team_name)

                # --- NEW DEBUGGING ---
                if team_id is None:
                    logging.warning(f"Lookup failed for team: '{team_name}' (Original from transactions: '{player['fantasy_team']}')")
                # --- END DEBUGGING ---

                if not team_id:
                    logging.warning(f"Skipping player {player['player_name']}: could not find team_id for team '{team_name}'.")
                    continue

                player_id_str = str(player['player_id'])
                player_stats = {'Player': player['player_name'], 'GP': 0}

                # --- REVERTED: Query 1: Check for 'g' in daily_player_stats ---
                cursor.execute("""
                    SELECT 1
                    FROM daily_player_stats
                    WHERE CAST(player_id AS TEXT) = ? AND team_id = ?
                      AND date_ >= ? AND date_ <= ?
                      AND lineup_pos = 'g'
                    LIMIT 1
                """, (player_id_str, team_id, start_date, end_date))
                is_goalie = cursor.fetchone() is not None
                # --- END REVERTED ---

                # --- Query 2: Get aggregated stats (simplified) ---
                cursor.execute("""
                    SELECT category, SUM(stat_value) as total
                    FROM daily_player_stats
                    WHERE CAST(player_id AS TEXT) = ? AND team_id = ?
                      AND date_ >= ? AND date_ <= ?
                    GROUP BY category
                """, (player_id_str, team_id, start_date, end_date))

                stats_raw = cursor.fetchall()
                player_stat_map = {row['category']: row['total'] for row in stats_raw}

                # --- MODIFIED: Query 3: Get Games Played with non-zero stats *for that team* ---
                cursor.execute("""
                    SELECT COUNT(T.date_) as games_played
                    FROM (
                        SELECT date_, SUM(stat_value) as total_stats
                        FROM daily_player_stats
                        WHERE CAST(player_id AS TEXT) = ? AND team_id = ?
                          AND date_ >= ? AND date_ <= ?
                        GROUP BY date_
                        HAVING total_stats > 0
                    ) T
                """, (player_id_str, team_id, start_date, end_date))

                gp_row = cursor.fetchone()
                if gp_row:
                    player_stats['GP'] = gp_row['games_played']
                # --- END MODIFIED ---

                # --- MODIFIED: Populate based on position and fill 0s ---
                if is_goalie:
                    # --- NEW: Calculate SVpct and GAA ---
                    sv = player_stat_map.get('SV', 0)
                    sa = player_stat_map.get('SA', 0)
                    ga = player_stat_map.get('GA', 0)
                    toi = player_stat_map.get('TOI/G', 0) # Assumes 'TOI/G' is the time-on-ice stat

                    if 'SVpct' in goalie_categories:
                        player_stat_map['SVpct'] = (sv / sa) if sa > 0 else 0.0

                    if 'GAA' in goalie_categories:
                        player_stat_map['GAA'] = ((float(ga) * 60) / toi) if toi > 0 else 0.0
                    # --- END NEW ---

                    for cat in goalie_categories:
                        player_stats[cat] = player_stat_map.get(cat, 0)

                    # --- NEW: Add sub-stats for JS to use ---
                    player_stats['SV'] = sv
                    player_stats['SA'] = sa
                    player_stats['GA'] = ga
                    player_stats['TOI/G'] = toi
                    # --- END NEW ---

                    league_data[team_name]['goalies'].append(player_stats)
                else:
                    for cat in skater_categories:
                        player_stats[cat] = player_stat_map.get(cat, 0)
                    league_data[team_name]['skaters'].append(player_stats)
                # --- END MODIFIED ---

            return jsonify({
                'view_mode': 'league',
                'league_data': league_data,
                # --- MODIFIED: Send separate headers ---
                'skater_stat_headers': skater_categories,
                'goalie_stat_headers': goalie_categories,
                # --- END MODIFIED ---
                'is_weekly_view': True # League view is always weekly for now
            })

    except Exception as e:
        logging.error(f"Error fetching transaction data: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/history/category_strengths', methods=['POST'])
def get_category_strengths_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg}), 404

    try:
        cursor = conn.cursor()
        data = request.get_json()
        selected_team_name = data.get('team_name')
        week = data.get('week')

        logging.info("--- Category Strengths Report (League) ---")
        logging.info(f"Selected team: {selected_team_name}, week: '{week}'")

        # 1. Get *all* teams from the DB
        cursor.execute("SELECT team_id, name FROM teams")
        all_teams_raw = cursor.fetchall()

        teams_map_id_to_name = {str(row['team_id']): row['name'].decode('utf-8').strip() for row in all_teams_raw}
        teams_map_name_to_id = {v: k for k, v in teams_map_id_to_name.items()}

        if selected_team_name not in teams_map_name_to_id:
             return jsonify({'error': f'Team not found: {selected_team_name}'}), 404

        selected_team_id = teams_map_name_to_id[selected_team_name]

        # 2. Get Dates and Opponent
        start_date, end_date = None, None
        opponent_name = None

        if week != 'all':
            try:
                week_num_int = int(week)
                cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num_int,))
                week_dates = cursor.fetchone()

                if week_dates:
                    start_date = week_dates['start_date']
                    end_date = week_dates['end_date']
                    logging.info(f"Found week dates: {start_date} to {end_date}")

                    cursor.execute(
                        "SELECT team1, team2 FROM matchups WHERE week = ? AND (CAST(team1 AS TEXT) = ? OR CAST(team2 AS TEXT) = ?)",
                        (week_num_int, selected_team_name, selected_team_name)
                    )
                    matchup_row = cursor.fetchone()
                    if matchup_row:
                        matchup_row_decoded = decode_dict_values(dict(matchup_row))
                        opponent_name = matchup_row_decoded['team2'] if matchup_row_decoded['team1'] == selected_team_name else matchup_row_decoded['team1']
                        logging.info(f"Found opponent_name: {opponent_name}")
                    else:
                        logging.warning(f"Could not find matchup row for week = {week_num_int}")
                else:
                    logging.warning(f"Could not find week_num = {week_num_int}")
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid week format.'}), 400
        else:
            logging.info("Week is 'all', aggregating all season stats.")

        # 3. Get Scoring Categories
        cursor.execute("SELECT category, scoring_group FROM scoring ORDER BY scoring_group DESC, stat_id")
        all_categories_raw = cursor.fetchall()
        skater_categories = [row['category'] for row in all_categories_raw if row['scoring_group'] == 'offense']
        goalie_categories = [row['category'] for row in all_categories_raw if row['scoring_group'] == 'goaltending']
        all_scoring_categories = set(skater_categories + goalie_categories)
        categories_to_fetch = all_scoring_categories | {'SV', 'SA', 'GA', 'TOI/G'}

        # --- NEW: Define reverse scoring categories ---
        reverse_scoring_cats = {'GA', 'GAA'}

        # 4. Build and execute the *league-wide* aggregation query
        sql_params = []
        sql_query = """
            SELECT team_id, category, SUM(stat_value) as total
            FROM daily_player_stats
        """

        if start_date and end_date: # Week-specific
            sql_query += " WHERE date_ >= ? AND date_ <= ?"
            sql_params.extend([start_date, end_date])
        elif week != 'all': # Week was selected but no dates found (error)
             sql_query += " WHERE 1=0" # Force no results

        sql_query += " GROUP BY team_id, category"

        cursor.execute(sql_query, tuple(sql_params))
        raw_stats = decode_dict_values([dict(row) for row in cursor.fetchall()])
        logging.info(f"Found {len(raw_stats)} aggregated stat rows for the whole league.")

        # 5. Pivot data for *all* teams and recalculate derived stats
        all_team_stats = {
            team_id: {cat: 0 for cat in categories_to_fetch}
            for team_id in teams_map_id_to_name
        }

        for row in raw_stats:
            team_id = str(row['team_id'])
            if team_id in all_team_stats and row['category'] in all_team_stats[team_id]:
                all_team_stats[team_id][row['category']] = row.get('total', 0)

        for team_id in all_team_stats:
            stats = all_team_stats[team_id]
            sv = stats.get('SV', 0)
            sa = stats.get('SA', 0)
            ga = stats.get('GA', 0)
            toi = stats.get('TOI/G', 0)
            sho = stats.get('SHO', 0)

            if sho > 0:
                toi += (sho * 60)
                stats['TOI/G'] = toi

            if 'GAA' in stats:
                stats['GAA'] = (ga * 60) / toi if toi > 0 else 0
            if 'SVpct' in stats:
                stats['SVpct'] = sv / sa if sa > 0 else 0

        # --- NEW: Get list of opponent IDs ---
        opponent_team_ids = [team_id for team_id in all_team_stats if team_id != selected_team_id]
        num_opponents = len(opponent_team_ids)

        # 6. Determine Column Order
        team_headers = []
        team_headers.append(selected_team_name)

        other_team_names = [name for name in teams_map_name_to_id if name != selected_team_name]

        if opponent_name:
            team_headers.append(opponent_name)
            if opponent_name in other_team_names:
                other_team_names.remove(opponent_name)

        team_headers.extend(sorted(other_team_names))
        logging.info(f"Team header order: {team_headers}")

        # 7. Format data for vertical table output
        skater_data_rows = []
        for cat in skater_categories:
            row = {'category': cat}
            my_value = all_team_stats[selected_team_id].get(cat, 0)
            is_reverse = cat in reverse_scoring_cats

            # --- Calculate Rank ---
            all_values = [all_team_stats[team_id].get(cat, 0) for team_id in all_team_stats]
            # Use set() for a dense rank (e.g., 1, 2, 2, 3)
            sorted_values = sorted(list(set(all_values)), reverse=(not is_reverse))
            row['Rank'] = sorted_values.index(my_value) + 1

            # --- Calculate Average Delta ---
            if num_opponents > 0:
                opponent_values = [all_team_stats[team_id].get(cat, 0) for team_id in opponent_team_ids]
                deltas = [my_value - opp_value for opp_value in opponent_values]
                avg_delta = sum(deltas) / num_opponents
                if is_reverse:
                    avg_delta = -avg_delta # Flip sign so positive is always "good"
                row['Average Delta'] = round(avg_delta, 2)
            else:
                row['Average Delta'] = 0

            # --- Add team stats ---
            for team_name in team_headers:
                team_id = teams_map_name_to_id[team_name]
                value = all_team_stats[team_id].get(cat, 0)
                row[team_name] = round(value, 1)
            skater_data_rows.append(row)

        goalie_data_rows = []
        for cat in goalie_categories:
            row = {'category': cat}
            my_value = all_team_stats[selected_team_id].get(cat, 0)
            is_reverse = cat in reverse_scoring_cats

            # --- Calculate Rank ---
            all_values = [all_team_stats[team_id].get(cat, 0) for team_id in all_team_stats]
            sorted_values = sorted(list(set(all_values)), reverse=(not is_reverse))
            row['Rank'] = sorted_values.index(my_value) + 1

            # --- Calculate Average Delta ---
            if num_opponents > 0:
                opponent_values = [all_team_stats[team_id].get(cat, 0) for team_id in opponent_team_ids]
                deltas = [my_value - opp_value for opp_value in opponent_values]
                avg_delta = sum(deltas) / num_opponents
                if is_reverse:
                    avg_delta = -avg_delta # Flip sign so positive is always "good"
                row['Average Delta'] = round(avg_delta, 2)
            else:
                row['Average Delta'] = 0

            # --- Add team stats ---
            for team_name in team_headers:
                team_id = teams_map_name_to_id[team_name]
                value = all_team_stats[team_id].get(cat, 0)

                if cat == 'GAA':
                    value = round(value, 2)
                elif cat == 'SVpct':
                    value = round(value, 3)
                else:
                    value = round(value, 1)
                row[team_name] = value
            goalie_data_rows.append(row)

        logging.info("--- Category Strengths Report End ---")
        return jsonify({
            'team_headers': team_headers,
            'skater_stats': skater_data_rows,
            'goalie_stats': goalie_data_rows
        })

    except Exception as e:
        logging.error(f"Error fetching category strengths data: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/roster_data', methods=['POST'])
def get_roster_data():
    league_id = session.get('league_id')
    data = request.get_json()
    week_num = data.get('week')
    team_name = data.get('team_name')
    simulated_moves = data.get('simulated_moves', [])

    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg}), 404

    try:
        cursor = conn.cursor()

        cursor.execute("SELECT category FROM scoring")
        all_scoring_categories = [row['category'] for row in cursor.fetchall()]

        checked_categories = data.get('categories')
        if checked_categories is None:
            checked_categories = all_scoring_categories

        unchecked_categories = [cat for cat in all_scoring_categories if cat not in checked_categories]
        # Get team ID
        cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (team_name,))
        team_id_row = cursor.fetchone()
        if not team_id_row:
            return jsonify({'error': f'Team not found: {team_name}'}), 404
        team_id = team_id_row['team_id']

        # Get week dates
        cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num,))
        week_dates = cursor.fetchone()
        if not week_dates:
            return jsonify({'error': f'Week not found: {week_num}'}), 404
        start_date = datetime.strptime(week_dates['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(week_dates['end_date'], '%Y-%m-%d').date()
        days_in_week = [(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]


        # Get next week's dates for the 'Next Week' column
        cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (int(week_num) + 1,))
        week_dates_next = cursor.fetchone()
        if not week_dates_next:
            start_date_next, end_date_next = None, None
        else:
            start_date_next = datetime.strptime(week_dates_next['start_date'], '%Y-%m-%d').date()
            end_date_next = datetime.strptime(week_dates_next['end_date'], '%Y-%m-%d').date()

        # Use the helper to get the ranked roster of active players
        active_players = _get_ranked_roster_for_week(cursor, team_id, week_num)

        # Get the full player list for display, including IR players
        cursor.execute("""
            SELECT p.player_name, p.player_team as team, rp.eligible_positions, p.player_name_normalized
            FROM rosters_tall r
            JOIN rostered_players rp ON r.player_id = rp.player_id
            JOIN players p ON rp.player_id = p.player_id
            WHERE r.team_id = ?
        """, (team_id,))
        all_players_raw = cursor.fetchall()
        all_players = decode_dict_values([dict(row) for row in all_players_raw])

        if simulated_moves:
            dropped_player_ids = {int(m['dropped_player']['player_id']) for m in simulated_moves}
            # Filter out dropped players
            all_players = [p for p in all_players if int(p.get('player_id', 0)) not in dropped_player_ids]
            # Add added players
            for move in simulated_moves:
                all_players.append(move['added_player'])


        # Get scoring categories to fetch rank columns
        cursor.execute("SELECT category FROM scoring")
        scoring_categories = [row['category'] for row in cursor.fetchall()]
        cat_rank_columns = [f"{cat}_cat_rank" for cat in scoring_categories]

        # Get player stats for all players to populate rank columns
        all_normalized_names = [p.get('player_name_normalized') for p in all_players]
        # Filter out the 'None' entries so the SQL query doesn't fail
        valid_normalized_names = [name for name in all_normalized_names if name]

        player_stats = {}
        if valid_normalized_names: # Only query if we have valid names
            placeholders = ','.join('?' for _ in valid_normalized_names)
            query = f"""
                SELECT player_name_normalized, {', '.join(cat_rank_columns)}
                FROM joined_player_stats WHERE player_name_normalized IN ({placeholders})
            """
            cursor.execute(query, valid_normalized_names) # Use the filtered list
            player_stats = {row['player_name_normalized']: dict(row) for row in cursor.fetchall()}

        # Augment the full player list with all necessary data
        player_custom_rank_map = {}
        active_player_map = {p['player_name']: p for p in active_players}
        for player in all_players:
            # Add ranks and this week's schedule from the active player data
            if player['player_name'] in active_player_map:
                # This is a base roster player, get their schedule
                source = active_player_map[player['player_name']]
                player['total_rank'] = source.get('total_rank')
                player['game_dates_this_week'] = source.get('game_dates_this_week', [])
                player['games_this_week'] = [datetime.strptime(d, '%Y-%m-%d').strftime('%a') for d in player['game_dates_this_week']]
            else:
                # This is either an IR player or a Simulated Player
                # If 'games_this_week' is NOT on the object, it's an IR player. Set to [].
                # If 'games_this_week' IS on the object, it's a Simulated Player. Do nothing, leave its data intact.
                if 'games_this_week' not in player:
                    player['games_this_week'] = []
                if 'game_dates_this_week' not in player:
                    player['game_dates_this_week'] = []

            p_stats = player_stats.get(player.get('player_name_normalized'))
            new_total_rank = 0
            if p_stats:
                for cat in all_scoring_categories:
                    rank_key = f"{cat}_cat_rank"
                    rank_value = p_stats.get(rank_key)

                    # Store individual rank for the table
                    player[rank_key] = round(rank_value, 2) if rank_value is not None else None

                    # Calculate custom total_rank
                    if rank_value is not None:
                        if cat in unchecked_categories:
                            new_total_rank += rank_value / 10.0
                        else:
                            new_total_rank += rank_value
            player['total_rank'] = round(new_total_rank, 2) if p_stats else None
            if player.get('player_id'):
                player_custom_rank_map[int(player['player_id'])] = player['total_rank']
            # Add category ranks for all players (active and inactive)
#            p_stats = player_stats.get(player['player_name_normalized'])
#            if p_stats:
#                for cat in scoring_categories:
#                    rank_key = f"{cat}_cat_rank"
#                    player[rank_key] = round(p_stats.get(rank_key), 2) if p_stats.get(rank_key) is not None else None

            player['games_next_week'] = []
            if start_date_next and end_date_next:
                player_team_tricode = player.get('team') or player.get('player_team')

                if player_team_tricode: # Only proceed if we found a team tricode
                    cursor.execute("SELECT schedule_json FROM team_schedules WHERE team_tricode = ?", (player_team_tricode,))
                    schedule_row = cursor.fetchone()
                    if schedule_row and schedule_row['schedule_json']:
                        schedule = json.loads(schedule_row['schedule_json'])
                        for game_date_str in schedule:
                            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
                            if start_date_next <= game_date <= end_date_next:
                                player['games_next_week'].append(game_date.strftime('%a'))

        logging.info("Updating ranks for active_players list...")
        for player in active_players:
            custom_rank = player_custom_rank_map.get(int(player.get('player_id', 0)))
            if custom_rank is not None:
                player['total_rank'] = custom_rank
            elif player.get('total_rank') is None: # Fallback for players w/o stats
                player['total_rank'] = 60

        # 2. Update simulated_moves list
        logging.info("Updating ranks for simulated_moves list...")
        for move in simulated_moves:
            added_player = move['added_player']
            # Use int for robust matching
            custom_rank = player_custom_rank_map.get(int(added_player.get('player_id', 0)))
            if custom_rank is not None:
                added_player['total_rank'] = custom_rank
            elif added_player.get('total_rank') is None: # Fallback
                added_player['total_rank'] = 60
        logging.info("Finished updating ranks for active_players.")

# We don't need to store individual cat ranks here
# as they are already on the player object from _get_ranked_roster_for_week
#if rank_value is not None:
#    if cat in unchecked_categories:
#        new_total_rank += rank_value / 10.0 # Using your / 10.0 logic
#    else:
#        new_total_rank += rank_value


        # Get lineup settings
        cursor.execute("SELECT position, position_count FROM lineup_settings WHERE position NOT IN ('BN', 'IR', 'IR+')")
        lineup_settings = {row['position']: row['position_count'] for row in cursor.fetchall()}

# --- Calculate optimal lineup and starts for each day ---
        daily_optimal_lineups = {}
        player_starts_counter = Counter()

        for day_date in days_in_week:
            day_str = day_date.strftime('%Y-%m-%d')

            daily_active_roster = _get_daily_simulated_roster(active_players, simulated_moves, day_str)

            players_playing_today = []
            for p in daily_active_roster:
                # Check both keys for safety (base roster vs. sim player)
                game_dates = p.get('game_dates_this_week') or p.get('game_dates_this_week_full', [])
                if day_str in game_dates:
                    players_playing_today.append(p)

            if players_playing_today:
                optimal_lineup_for_day = get_optimal_lineup(
                    players_playing_today,
                    lineup_settings
                )
                display_date = day_date.strftime('%A, %b %d')
                daily_optimal_lineups[display_date] = optimal_lineup_for_day

                for pos_players in optimal_lineup_for_day.values():
                    for player in pos_players:
                        # Use player_id for counter, it's more reliable
                        player_starts_counter[player['player_id']] += 1

        # Add starts count to the final player list
        for player in all_players:
            player['starts_this_week'] = player_starts_counter.get(player.get('player_id'), 0)

        # --- Calculate Unused Roster Spots ---
        unused_roster_spots = _calculate_unused_spots(days_in_week, active_players, lineup_settings, simulated_moves)

        return jsonify({
            'players': all_players,
            'daily_optimal_lineups': daily_optimal_lineups,
            'scoring_categories': all_scoring_categories,
            'lineup_settings': lineup_settings,
            'checked_categories': checked_categories,
            'unused_roster_spots': unused_roster_spots
        })

    except Exception as e:
        logging.error(f"Error fetching roster data: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/free_agent_data', methods=['GET', 'POST'])
def get_free_agent_data():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)

    if not conn:
        return jsonify({'error': error_msg}), 404

    try:
        cursor = conn.cursor()
        request_data = request.get_json(silent=True) or {}

        # Get all scoring categories from the database
        cursor.execute("SELECT category FROM scoring")
        all_scoring_categories = [row['category'] for row in cursor.fetchall()]

        # Determine which categories are checked. If none are sent, assume all are.
        checked_categories = request_data.get('categories')
        if checked_categories is None:
            checked_categories = all_scoring_categories

        unchecked_categories = [cat for cat in all_scoring_categories if cat not in checked_categories]

        all_cat_rank_columns = [f"{cat}_cat_rank" for cat in all_scoring_categories]

        # Determine current week
        today = date.today().isoformat()
        cursor.execute("SELECT week_num FROM weeks WHERE start_date <= ? AND end_date >= ?", (today, today))
        current_week_row = cursor.fetchone()
        current_week = current_week_row['week_num'] if current_week_row else 1

        cursor.execute("SELECT player_id FROM waiver_players")
        waiver_player_ids = [row['player_id'] for row in cursor.fetchall()]
        waiver_players = _get_ranked_players(cursor, waiver_player_ids, all_cat_rank_columns, current_week)

        cursor.execute("SELECT player_id FROM free_agents")
        free_agent_ids = [row['player_id'] for row in cursor.fetchall()]
        free_agents = _get_ranked_players(cursor, free_agent_ids, all_cat_rank_columns, current_week)

        # Recalculate total_cat_rank based on checked/unchecked categories
        for player_list in [waiver_players, free_agents]:
            for player in player_list:
                total_rank = 0
                for cat in all_scoring_categories:
                    rank_key = f"{cat}_cat_rank"
                    rank_value = player.get(rank_key)
                    if rank_value is not None:
                        if cat in unchecked_categories:
                            total_rank += rank_value / 2.0  # Halve the value for unchecked categories
                        else:
                            total_rank += rank_value
                player['total_cat_rank'] = round(total_rank, 2)

        # --- Calculate Unused Roster Spots for the SELECTED Team ---
        unused_roster_spots = None
        team_ranked_roster = []
        days_in_week_data = []
        selected_team_name = request_data.get('team_name')

        # --- [START] THE FIX ---
        # 1. Get the simulated moves list from the request
        simulated_moves = request_data.get('simulated_moves', [])
        # --- [END] THE FIX ---

        if selected_team_name:
            cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (selected_team_name,))
            team_row = cursor.fetchone()
            if team_row:
                team_id = team_row['team_id']
                cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (current_week,))
                week_dates = cursor.fetchone()
                if week_dates:
                    start_date_obj = datetime.strptime(week_dates['start_date'], '%Y-%m-%d').date()
                    end_date_obj = datetime.strptime(week_dates['end_date'], '%Y-%m-%d').date()
                    days_in_week = [(start_date_obj + timedelta(days=i)) for i in range((end_date_obj - start_date_obj).days + 1)]

                    today_obj = date.today()
                    for day in days_in_week:
                        if day >= today_obj:
                            days_in_week_data.append(day.isoformat())

                    cursor.execute("SELECT position, position_count FROM lineup_settings WHERE position NOT IN ('BN', 'IR', 'IR+')")
                    lineup_settings = {row['position']: row['position_count'] for row in cursor.fetchall()}

                    team_ranked_roster = _get_ranked_roster_for_week(cursor, team_id, current_week)

                    # --- [START] THE FIX ---
                    # 2. Pass the simulated_moves list to the helper function
                    unused_roster_spots = _calculate_unused_spots(days_in_week, team_ranked_roster, lineup_settings, simulated_moves)
                    # --- [END] THE FIX ---

        # Get all scoring categories for checkboxes
        cursor.execute("SELECT category FROM scoring")
        all_scoring_categories_for_checkboxes = [row['category'] for row in cursor.fetchall()]

        return jsonify({
            'waiver_players': waiver_players,
            'free_agents': free_agents,
            'scoring_categories': all_scoring_categories_for_checkboxes,
            'ranked_categories': all_scoring_categories,
            'checked_categories': checked_categories,
            'unused_roster_spots': unused_roster_spots,
            'team_roster': [dict(p) for p in team_ranked_roster],
            'week_dates': days_in_week_data
        })

    except Exception as e:
        logging.error(f"Error fetching free agent data: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


def _get_team_goalie_stats(cursor, team_id, start_date_str, end_date_str):
    # 1. Get Aggregated Live Stats
    goalie_categories = ['W', 'L', 'GA', 'SV', 'SA', 'SHO', 'TOI/G']

    cursor.execute(f"""
        SELECT category, SUM(stat_value) as total
        FROM daily_player_stats
        WHERE date_ >= ? AND date_ <= ? AND team_id = ?
        AND category IN ({','.join('?' for _ in goalie_categories)})
        GROUP BY category
    """, (start_date_str, end_date_str, team_id, *goalie_categories))

    live_stats_raw = cursor.fetchall()
    live_stats_decoded = decode_dict_values([dict(row) for row in live_stats_raw])

    live_stats = {cat: 0 for cat in goalie_categories}
    for row in live_stats_decoded:
        if row['category'] in live_stats:
            live_stats[row['category']] = row.get('total', 0)

    if 'SHO' in live_stats and live_stats['SHO'] > 0:
        live_stats['TOI/G'] += (live_stats['SHO'] * 60)

    # 2. Get Individual Goalie Starts
    cursor.execute("""
        SELECT
            d.player_id,
            p.player_name,
            d.date_,
            d.category,
            d.stat_value
        FROM daily_player_stats d
        JOIN players p ON d.player_id = p.player_id
        WHERE d.team_id = ? AND d.date_ >= ? AND d.date_ <= ?
        AND d.category IN ('W', 'L', 'GA', 'SV', 'SA', 'SHO', 'TOI/G')
        ORDER BY d.date_, p.player_name
    """, (team_id, start_date_str, end_date_str))

    raw_starts = cursor.fetchall()

    starts_data = defaultdict(lambda: defaultdict(float))
    for row in raw_starts:
        key = (row['player_id'], row['player_name'], row['date_'])
        starts_data[key][row['category']] = row['stat_value']

    individual_starts = []
    for (player_id, player_name, date_), stats in starts_data.items():
        if stats.get('SA', 0) > 0:
            start_record = {
                "player_id": player_id,
                "player_name": player_name,
                "date": date_,
                **stats
            }

            toi = stats.get('TOI/G', 0)
            if stats.get('SHO', 0) > 0:
                toi += 60
                start_record['TOI/G'] = toi

            start_record['GAA'] = (stats.get('GA', 0) * 60) / toi if toi > 0 else 0
            start_record['SV%'] = stats.get('SV', 0) / stats.get('SA', 0) if stats.get('SA', 0) > 0 else 0

            individual_starts.append(start_record)

    goalie_starts = len(individual_starts)

    return {
        'live_stats': live_stats,
        'goalie_starts': goalie_starts,
        'individual_starts': individual_starts
    }


@app.route('/api/goalie_planning_stats', methods=['POST'])
def get_goalie_planning_stats():
    league_id = session.get('league_id')
    data = request.get_json()
    week_num = data.get('week')
    your_team_name = data.get('your_team_name')
    opponent_team_name = data.get('opponent_team_name')

    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg}), 404

    try:
        cursor = conn.cursor()

        # Get Team IDs
        cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (your_team_name,))
        your_team_id_row = cursor.fetchone()

        cursor.execute("SELECT team_id FROM teams WHERE CAST(name AS TEXT) = ?", (opponent_team_name,))
        opponent_team_id_row = cursor.fetchone()

        if not your_team_id_row:
            return jsonify({'error': f'Team not found: {your_team_name}'}), 404
        if not opponent_team_id_row:
            return jsonify({'error': f'Team not found: {opponent_team_name}'}), 404

        your_team_id = your_team_id_row['team_id']
        opponent_team_id = opponent_team_id_row['team_id']

        # Get week dates
        cursor.execute("SELECT start_date, end_date FROM weeks WHERE week_num = ?", (week_num,))
        week_dates = cursor.fetchone()
        if not week_dates:
            return jsonify({'error': f'Week not found: {week_num}'}), 404
        start_date_str = week_dates['start_date']
        end_date_str = week_dates['end_date']

        # Get stats for both teams using the helper
        your_team_stats = _get_team_goalie_stats(cursor, your_team_id, start_date_str, end_date_str)
        opponent_team_stats = _get_team_goalie_stats(cursor, opponent_team_id, start_date_str, end_date_str)

        return jsonify({
            'your_team_stats': your_team_stats,
            'opponent_team_stats': opponent_team_stats
        })

    except Exception as e:
        logging.error(f"Error fetching goalie planning stats: {e}", exc_info=True)
        return jsonify({'error': f"An error occurred: {e}"}), 500
    finally:
        if conn:
            conn.close()


@app.route('/stream')
def stream():
    def event_stream():
        while True:
            message = log_queue.get()
            if message is None:
                break
            yield f"data: {message}\n\n"
    return Response(event_stream(), mimetype='text/event-stream')

#def update_db_in_background(yq, lg, league_id, data_dir, capture_lineups, skip_static_info, skip_available_players):
def update_db_in_background(yq, lg, league_id, data_dir, capture_lineups):
    """Function to run in a separate thread."""
    try:
        db_builder.update_league_db(
            yq, lg, league_id, data_dir,
            capture_lineups=capture_lineups#,
#            skip_static_info=skip_static_info,
#            skip_available_players=skip_available_players
        )
        log_queue.put("SUCCESS: Database update complete.")
    except Exception as e:
        logging.error(f"Error in background DB update: {e}", exc_info=True)
        log_queue.put(f"ERROR: {e}")
    finally:
        # Signal the end of the stream
        log_queue.put(None)

@app.route('/api/update_db', methods=['POST'])
def update_db_route():
    if session.get('dev_mode'):
        return jsonify({'success': False, 'error': 'Database updates are disabled in dev mode.'}), 403

    yq = get_yfpy_instance()
    lg = get_yfa_lg_instance()
    if not yq or not lg:
        return jsonify({"error": "Authentication failed. Please log in again."}), 401

    league_id = session.get('league_id')
    if not league_id:
        return jsonify({'success': False, 'error': 'League ID not found in session.'}), 400

    data = request.get_json() or {}
    capture_lineups = data.get('capture_lineups', False)
#    skip_static_info = data.get('skip_static_info', False)
#    skip_available_players = data.get('skip_available_players', False)

    # Run the database update in a background thread
    thread = threading.Thread(
        target=update_db_in_background,
        args=(yq, lg, league_id, DATA_DIR, capture_lineups)#, skip_static_info, skip_available_players)
    )
    thread.start()

    return jsonify({'success': True, 'message': 'Database update started.'})


@app.route('/api/download_db')
def download_db():
    if session.get('use_test_db'):
        logging.info(f"Downloading test database: {TEST_DB_FILENAME}")
        if not os.path.exists(TEST_DB_PATH):
            return jsonify({'error': 'Test database file not found in /server directory.'}), 404
        return send_from_directory(SERVER_DIR, TEST_DB_FILENAME, as_attachment=True)

    league_id = session.get('league_id')
    if not league_id:
        return jsonify({'error': 'Not logged in or session expired.'}), 401

    db_filename = None
    for filename in os.listdir(DATA_DIR):
        if filename.startswith(f"yahoo-{league_id}-") and filename.endswith(".db"):
            db_filename = filename
            break

    if not db_filename:
        return jsonify({'error': 'Database file not found. Please create it on the "League Database" page first.'}), 404

    try:
        return send_from_directory(DATA_DIR, db_filename, as_attachment=True)
    except Exception as e:
        logging.error(f"Error sending database file: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while trying to download the file.'}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify({
            'use_test_db': session.get('use_test_db', False),
            'test_db_exists': os.path.exists(TEST_DB_PATH)
        })
    elif request.method == 'POST':
        data = request.get_json()
        use_test_db = data.get('use_test_db', False)

        # Dev mode forces the test DB on, don't let it be turned off
        if session.get('dev_mode'):
             session['use_test_db'] = True
        else:
            session['use_test_db'] = use_test_db

        logging.info(f"Test DB mode set to: {session['use_test_db']}")
        return jsonify({'success': True, 'use_test_db': session['use_test_db']})

@app.route('/api/db_timestamp')
def db_timestamp():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg or "Database not found."}), 404

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM db_metadata WHERE key = 'last_updated_timestamp'")
        row = cursor.fetchone()
        timestamp = row['value'] if row else None
        return jsonify({'timestamp': timestamp})
    except Exception as e:
        logging.error(f"Error fetching timestamp: {e}", exc_info=True)
        return jsonify({'error': 'Could not retrieve timestamp.'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/available_players_timestamp')
def available_players_timestamp():
    league_id = session.get('league_id')
    conn, error_msg = get_db_connection_for_league(league_id)
    if not conn:
        return jsonify({'error': error_msg or "Database not found."}), 404

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM db_metadata WHERE key = 'available_players_last_updated_timestamp'")
        row = cursor.fetchone()
        timestamp = row['value'] if row else None
        return jsonify({'timestamp': timestamp})
    except Exception as e:
        logging.error(f"Error fetching available players timestamp: {e}", exc_info=True)
        return jsonify({'error': 'Could not retrieve timestamp.'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/pages/<path:page_name>')
def serve_page(page_name):
    return render_template(f"pages/{page_name}")

@app.route('/api/db_status')
def db_status():
    if session.get('use_test_db'):
        db_exists = os.path.exists(TEST_DB_PATH)
        timestamp = os.path.getmtime(TEST_DB_PATH) if db_exists else None
        return jsonify({
            'db_exists': db_exists,
            'league_name': f"TEST DB: {TEST_DB_FILENAME}",
            'timestamp': int(timestamp) if timestamp else None,
            'is_test_db': True
        })

    league_id = session.get('league_id')
    if not league_id:
        return jsonify({'db_exists': False, 'error': 'Not logged in.', 'is_test_db': False})

    db_path = None
    league_name = "[Unknown]"
    timestamp = None
    db_exists = False
    db_filename = None

    for filename in os.listdir(DATA_DIR):
        if filename.startswith(f"yahoo-{league_id}-") and filename.endswith(".db"):
            db_path = os.path.join(DATA_DIR, filename)
            db_exists = True
            db_filename = filename
            break

    if db_exists:
        try:
            match = re.search(f"yahoo-{league_id}-(.*)\\.db", db_filename)
            if match:
                league_name = match.group(1)
            timestamp = os.path.getmtime(db_path)
        except Exception as e:
            logging.error(f"Could not parse DB file info: {e}")
            return jsonify({'db_exists': False, 'error': 'Could not read database file details.', 'is_test_db': False})

    return jsonify({
        'db_exists': db_exists,
        'league_name': league_name,
        'timestamp': int(timestamp) if timestamp else None,
        'is_test_db': False
    })


# --- MODIFIED: This entire route is corrected ---
@app.route('/api/db_action', methods=['POST'])
def db_action():
    # --- FIX 1: Check for 'yahoo_token' (from /callback) not 'oauth_token' ---
    if not session.get('yahoo_token'):
        return jsonify({'error': 'Not authenticated'}), 401

    league_id = session.get('league_id')
    if not league_id:
        return jsonify({'error': 'No league selected'}), 400

    global db_build_status
    with db_build_status_lock:
        if db_build_status["running"]:
            return jsonify({'error': 'A build is already in progress.'}), 409
        db_build_status = {"running": True, "error": None}

    data = request.get_json()
    options = {
        'capture_lineups': data.get('capture_lineups', False),
        'skip_static': data.get('skip_static', False), # From your HTML
        'skip_players': data.get('skip_players', False) # From your HTML
    }

    # --- FIX 2: Get all session data *before* starting the thread ---
    thread_data = {
        "league_id": league_id,
        "token": session.get('yahoo_token'),
        "consumer_key": session.get('consumer_key'),
        "consumer_secret": session.get('consumer_secret'),
        "dev_mode": session.get('dev_mode', False)
    }
    # --- End FIX 2 ---

    # --- Create session-specific build items ---
    build_id = str(uuid.uuid4())
    build_queue = Queue()
    with DB_QUEUES_LOCK:
        DB_BUILD_QUEUES[build_id] = build_queue

    def run_task(build_id, build_queue, options, data):
        # --- Create a temporary logger FOR THIS THREAD ONLY ---
        logger = logging.getLogger(f"db_build_{build_id}")
        logger.setLevel(logging.INFO)
        logger.propagate = False  # IMPORTANT: Do not send to root logger

        class QueueLogHandler(logging.Handler):
            def __init__(self, queue):
                super().__init__()
                self.queue = queue

            def emit(self, record):
                log_entry = self.format(record)
                self.queue.put(f"{log_entry}\n")

        queue_handler = QueueLogHandler(build_queue)
        queue_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        queue_handler.setFormatter(formatter)

        if not logger.handlers:
            logger.addHandler(queue_handler)
        # --- END NEW LOGGER SETUP ---

        yq = None
        lg = None

        try:
            # --- FIX 3: Instantiate API objects *inside* the thread ---
            if not data.get('dev_mode'):
                # 3a. Create yfpy (yq) instance
                auth_data = {
                    'consumer_key': data['consumer_key'],
                    'consumer_secret': data['consumer_secret'],
                    'access_token': data['token'].get('access_token'),
                    'refresh_token': data['token'].get('refresh_token'),
                    'token_type': data['token'].get('token_type', 'bearer'),
                    'token_time': data['token'].get('expires_at', time.time() + 3600),
                    'guid': data['token'].get('xoauth_yahoo_guid')
                }
                yq = YahooFantasySportsQuery(
                    data['league_id'],
                    game_code="nhl",
                    yahoo_access_token_json=auth_data
                )

                # 3b. Create yfa (lg) instance
                # We must create a new temp file for this thread
                creds = {
                    "consumer_key": data['consumer_key'],
                    "consumer_secret": data['consumer_secret'],
                    "access_token": data['token'].get('access_token'),
                    "refresh_token": data['token'].get('refresh_token'),
                    "token_type": data['token'].get('token_type', 'bearer'),
                    "token_time": data['token'].get('expires_at', time.time() + 3600),
                    "xoauth_yahoo_guid": data['token'].get('xoauth_yahoo_guid')
                }
                temp_dir = os.path.join(DATA_DIR, 'temp_creds')
                os.makedirs(temp_dir, exist_ok=True)
                temp_file_path = os.path.join(temp_dir, f"thread_{build_id}.json")

                with open(temp_file_path, 'w') as f:
                    json.dump(creds, f)

                sc = OAuth2(None, None, from_file=temp_file_path)
                if not sc.token_is_valid():
                    logger.info("Thread token expired, refreshing...")
                    sc.refresh_access_token()

                gm = yfa.Game(sc, 'nhl')
                lg = gm.to_league(f"nhl.l.{data['league_id']}")

                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

            else:
                logger.info("Dev mode: Skipping real API object creation in thread.")
                # You might need mock objects here if db_builder fails without them
                yq = None
                lg = None

            logger.info("--- Starting Database Update ---")
            logger.info(f"League ID: {data['league_id']}")
            logger.info(f"Build ID: {build_id}")

            # --- FIX 4: Call the correct function from db_builder.py ---
            # And pass the new logger to it.
            result = db_builder.update_league_db(
                yq,
                lg,
                data['league_id'],
                DATA_DIR, # Pass the data directory
                logger, # Pass the new logger
                capture_lineups=options['capture_lineups']
                # Note: I am using the function from your db_builder.py file,
                # which does not include skip_static or skip_players.
                # If you re-add those to league-database.html, you must
                # add them here and to update_league_db in db_builder.py
            )
            # --- END FIX 4 ---

            if result and result.get('success'):
                logger.info(f"--- SUCCESS: {result.get('league_name')} updated. ---")
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"--- ERROR: {error_msg} ---")
                with db_build_status_lock:
                    db_build_status["error"] = error_msg

        except Exception as e:
            error_str = f"--- FATAL ERROR: {str(e)} ---"
            logger.error(error_str, exc_info=True)
            with db_build_status_lock:
                db_build_status["error"] = str(e)
        finally:
            with db_build_status_lock:
                db_build_status["running"] = False

            try:
                # Send the 'None' sentinel to tell any listener to stop
                build_queue.put(None, timeout=5)
            except Exception as e:
                logger.error(f"Build task {build_id} couldn't put sentinel in queue: {e}")

            # Give the listener a brief moment to receive the sentinel and disconnect
            time.sleep(1)

            # Now, this thread cleans up its own queue from the global dict
            with DB_QUEUES_LOCK:
                if build_id in DB_BUILD_QUEUES:
                    del DB_BUILD_QUEUES[build_id]
                    logger.info(f"Build task {build_id} cleaned up its own queue.")

    # --- Start thread with new thread_data arg ---
    threading.Thread(target=run_task, args=(build_id, build_queue, options, thread_data)).start()

    return jsonify({'success': True, 'build_id': build_id})
# --- END MODIFIED ROUTE ---


@app.route('/api/db_log_stream')
def db_log_stream():
    build_id = request.args.get('build_id')
    if not build_id:
        return Response("data: ERROR: No build_id provided.\n\ndata: __DONE__\n\n", mimetype='text/event-stream')

    with DB_QUEUES_LOCK:
        build_queue = DB_BUILD_QUEUES.get(build_id)

    if not build_queue:
        return Response(f"data: ERROR: Invalid build ID {build_id}. It may be complete or never existed.\n\ndata: __DONE__\n\n", mimetype='text/event-stream')

    def generate():
        # The try...finally block is removed.
        while True:
            try:
                message = build_queue.get(timeout=20)
                if message is None: # The sentinel from run_task
                    yield 'data: __DONE__\n\n'
                    break # Exit the loop
                message = message.strip()
                yield f"data: {message}\n\n"
            except: # queue.Empty exception
                # This keep-alive is fine
                yield ': keep-alive\n\n'

        # When the loop breaks (or client disconnects), this generator just ends.
        # It no longer deletes the queue.
        logging.info(f"Log stream {build_id} disconnected.")

    return Response(generate(), mimetype='text/event-stream')


# --- REMOVING OLD/DUPLICATE DB AND LOG ROUTES ---
# The routes /stream, /api/update_db, update_db_in_background
# and the second /api/db_status are all replaced by
# /api/db_action and /api/db_log_stream and the first /api/db_status
# --- END REMOVAL ---


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(debug=True, port=5001)
