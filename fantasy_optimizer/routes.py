"""
This module contains all the Flask routes (API endpoints) for the application.
It uses a Flask Blueprint to keep the routes organized and separate from the main
application initialization logic.
Updated: 10/3/2025
"""
import sqlite3
import json
import time
import re
import unicodedata
import os
from datetime import date, timedelta, datetime
from flask import Blueprint, jsonify, request, send_from_directory, session, url_for
import requests
from yahoo_fantasy_api import game
from . import config
from .auth import get_oauth_client
from .data_helpers import (
    get_user_leagues, get_weekly_roster_data, calculate_optimized_totals,
    get_live_stats_for_team, normalize_name, get_healthy_free_agents,
    enrich_fa_list_with_projections
)
from .optimization_logic import find_optimal_lineup

# Create a Blueprint. This is Flask's way of organizing groups of related routes.
api_bp = Blueprint('api', __name__)

# Server-side cache to avoid large session cookies
LEAGUE_DATA_CACHE = {}

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
        print("Token expired or nearing expiration, attempting to refresh manually...")
        try:
            with open(config.YAHOO_CREDENTIALS_FILE) as f:
                creds = json.load(f)

            redirect_uri = url_for('auth.callback', _external=True)
            if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
                redirect_uri = redirect_uri.replace('http://', 'https')

            payload = {
                'refresh_token': token_data['refresh_token'],
                'client_id': creds['consumer_key'],
                'client_secret': creds['consumer_secret'],
                'redirect_uri': redirect_uri,
                'grant_type': 'refresh_token'
            }

            token_url = '[https://api.login.yahoo.com/oauth2/get_token](https://api.login.yahoo.com/oauth2/get_token)'
            response = requests.post(token_url, data=payload)
            response.raise_for_status()

            new_token_data_from_refresh = response.json()

            # Update the existing token_data, don't replace it entirely.
            # This preserves the original xoauth_yahoo_guid.
            token_data['access_token'] = new_token_data_from_refresh['access_token']
            token_data['expires_in'] = new_token_data_from_refresh['expires_in']
            token_data['token_time'] = time.time()

            # If a new refresh token is provided, update that too.
            if 'refresh_token' in new_token_data_from_refresh:
                token_data['refresh_token'] = new_token_data_from_refresh['refresh_token']

            session['yahoo_token_data'] = token_data

            print("Successfully refreshed access token manually.")

        except Exception as e:
            print(f"Failed to refresh access token manually: {e}")
            session.clear()
            return None, (jsonify({"error": "Failed to refresh token, please log in again."}), 401)

    # Proceed with a valid token
    oauth = get_oauth_client(token_data)
    gm = game.Game(oauth, 'nhl')
    return gm, None

# --- Route to serve the main HTML file ---
@api_bp.route('/')
def index():
    """
    Serves the main index.html file from the project's root directory.
    We go 'up' one level from the current blueprint's directory.
    """
    # Use a more robust path to find the html file
    root_dir = os.path.join(os.path.dirname(__file__), '..')
    return send_from_directory(root_dir, 'index.html')

@api_bp.route('/players.html')
def players_page():
    """Serves the new players.html file."""
    # Use a more robust path to find the html file
    root_dir = os.path.join(os.path.dirname(__file__), '..')
    return send_from_directory(root_dir, 'players.html')


# --- API Routes ---

@api_bp.route("/api/cache-league-data")
def api_cache_league_data():
    """
    Fetches all necessary data for a league (rosters, FAs, live stats) from Yahoo,
    enriches it, and caches it in the server's memory.
    """
    league_id = request.args.get('league_id', type=str)
    week_num = request.args.get('week', type=int)
    # FIX: The key for the user GUID from yahoo-oauth is 'xoauth_yahoo_guid', not 'guid'
    user_guid = session.get('yahoo_token_data', {}).get('xoauth_yahoo_guid')

    if not all([week_num, league_id, user_guid]):
        return jsonify({"error": "Missing parameters or not authenticated"}), 400

    gm, error = check_auth_and_get_game()
    if error: return error

    try:
        cache_key = f"{user_guid}_{league_id}_{week_num}"

        print(f"Caching data for league {league_id}, week {week_num} with key {cache_key}...")
        lg = gm.to_league(league_id)

        # 1. Fetch all rosters (already projection-enriched)
        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters:
            return jsonify(all_rosters), 500

        # 2. Fetch available players from Yahoo
        available_players_raw = get_healthy_free_agents(lg)

        # 3. Enrich available players with projections from local DB
        enriched_available_players = enrich_fa_list_with_projections(available_players_raw, week_num)

        # 4. Fetch all live matchups for the week
        all_teams_data = lg.teams()
        live_stats_by_team = {}
        for team_key, team_info in all_teams_data.items():
            team_name = team_info['name']
            live_stats_by_team[team_name] = get_live_stats_for_team(lg, team_name, week_num)

        # 5. Store everything in the server-side cache
        LEAGUE_DATA_CACHE[cache_key] = {
            'rosters': all_rosters,
            'available_players': enriched_available_players,
            'live_stats': live_stats_by_team,
            'timestamp': time.time()
        }

        # Store only the key and identifiers in the session cookie
        session['cache_key'] = cache_key
        session['league_id'] = league_id
        session['week_num'] = week_num
        session.permanent = True

        print("Data successfully cached.")
        return jsonify(list(all_rosters.keys()))

    except Exception as e:
        print(f"An unexpected error in /api/cache-league-data: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500


@api_bp.route("/api/leagues")
def api_get_user_leagues():
    """API endpoint to get the logged-in user's fantasy leagues."""
    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        leagues = get_user_leagues(gm)
        return jsonify(leagues)
    except Exception as e:
        print(f"Error fetching leagues: {e}")
        return jsonify({"error": str(e)}), 500

@api_bp.route("/api/rosters/week/<int:week_num>")
def api_get_rosters_for_week(week_num):
    """API endpoint to get raw roster data, using the server-side cache if available."""
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)

    # Check if the requested week and league match what the key represents
    league_id = request.args.get('league_id', type=str)
    session_league_id = session.get('league_id')
    session_week_num = session.get('week_num')


    if cached_data and session_league_id == league_id and session_week_num == week_num:
        print("Serving rosters from cache.")
        return jsonify(cached_data['rosters'])

    # Fallback to live fetch if cache is invalid or missing
    print(f"Cache miss for rosters. Fetching live for league {league_id}, week {week_num}.")
    gm, error = check_auth_and_get_game()
    if error: return error
    rosters = get_weekly_roster_data(gm, league_id, week_num)
    if "error" in rosters: return jsonify(rosters), 500
    return jsonify(rosters)


@api_bp.route("/api/all-players")
def api_get_all_players():
    """
    API endpoint to get a team's roster and all available players (FA/W),
    pulling from the pre-loaded server-side cache.
    """
    team_name = request.args.get('team_name', type=str)
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)


    if not cached_data:
        return jsonify({"error": "No league data cached. Please select a league first."}), 400
    if not team_name:
        return jsonify({"error": "Missing team_name parameter"}), 400

    team_roster = cached_data['rosters'].get(team_name)
    if not team_roster:
        return jsonify({"error": f"Team '{team_name}' not found in cached data."}), 404

    return jsonify({
        "team_roster": team_roster,
        "available_players": cached_data['available_players']
    })


@api_bp.route("/api/matchup")
def api_get_matchup():
    """Gets matchup data from the server-side cache."""
    team1_name = request.args.get('team1', type=str)
    team2_name = request.args.get('team2', type=str)
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)
    week_num = session.get('week_num')

    if not all([team1_name, team2_name, cached_data, week_num]):
        return jsonify({"error": "Missing parameters or cached data"}), 400

    try:
        all_rosters = cached_data['rosters']
        live_stats = cached_data['live_stats']
        team1_roster = all_rosters.get(team1_name)
        team2_roster = all_rosters.get(team2_name)
        if not team1_roster or not team2_roster:
            return jsonify({"error": "One or both team names not found"}), 404

        con = sqlite3.connect(config.DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        full_week_dates = {'start': date.fromisoformat(week_info[0]), 'end': date.fromisoformat(week_info[1])}

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row[0]: json.loads(row[1]) for row in cur.fetchall()}

        cur.execute("SELECT off_day_date FROM off_days WHERE off_day_date >= ? AND off_day_date <= ?", (full_week_dates['start'].isoformat(), full_week_dates['end'].isoformat()))
        off_days = [row[0] for row in cur.fetchall()]
        con.close()

        team1_live_stats = live_stats.get(team1_name, {})
        team2_live_stats = live_stats.get(team2_name, {})

        def format_live_stats(stats):
            """Formats the raw live stats from Yahoo, rounding goalie rate stats."""
            formatted_stats = {}
            for key, value in stats.items():
                try:
                    num_value = float(value)
                    if key in ['svpct', 'gaa']:
                        formatted_stats[key] = round(num_value, 3)
                    else:
                        formatted_stats[key] = num_value
                except (ValueError, TypeError):
                    formatted_stats[key] = value
            return formatted_stats

        team1_current_stats = format_live_stats(team1_live_stats)
        team2_current_stats = format_live_stats(team2_live_stats)

        today = date.today()
        remainder_start = max(today, full_week_dates['start'])
        remainder_week_dates = {'start': remainder_start, 'end': full_week_dates['end']}

        team1_remainder, _, _ = calculate_optimized_totals(team1_roster, week_num, schedules, remainder_week_dates)
        team2_remainder, _, _ = calculate_optimized_totals(team2_roster, week_num, schedules, remainder_week_dates)

        def combine_stats(live, remainder):
            """Combines live and projected stats, correctly recalculating rate stats."""
            combined = {}
            # Combine all counting stats by simple addition
            all_keys = set(live.keys()) | set(remainder.keys())
            for key in all_keys:
                if key in ['svpct', 'gaa']: continue # Skip rate stats for now
                try:
                    combined[key] = float(live.get(key, 0)) + remainder.get(key, 0)
                except (ValueError, TypeError):
                    combined[key] = remainder.get(key, 0)

            # --- Recalculate Goalie Rate Stats ---
            try:
                live_ga = float(live.get('ga', 0))
                live_sv = float(live.get('sv', 0))
                live_svpct = float(live.get('svpct', 0))
                live_gaa = float(live.get('gaa', 0.0))
                # Approximate live stats from what Yahoo provides
                live_sa = live_sv / live_svpct if live_svpct > 0 else 0
                live_gs = live_ga / live_gaa if live_gaa > 0 else 0
            except (ValueError, TypeError):
                live_ga, live_sv, live_sa, live_gs = 0.0, 0.0, 0.0, 0.0

            rem_ga = remainder.get('raw_ga', 0)
            rem_sv = remainder.get('raw_sv', 0)
            rem_sa = remainder.get('raw_sa', 0)
            rem_gs = remainder.get('raw_gs', 0)

            total_ga = live_ga + rem_ga
            total_sv = live_sv + rem_sv
            total_sa = live_sa + rem_sa
            total_gs = live_gs + rem_gs

            # Update combined dictionary with correctly calculated rate stats
            # FIX: Round GAA and SV% to three decimal places for display.
            combined['gaa'] = round(total_ga / total_gs, 3) if total_gs > 0 else 0.0
            combined['svpct'] = round(total_sv / total_sa, 3) if total_sa > 0 else 0.0

            return combined


        team1_live_proj = combine_stats(team1_live_stats, team1_remainder)
        team2_live_proj = combine_stats(team2_live_stats, team2_remainder)

        return jsonify({
            team1_name: {"current_stats": team1_current_stats, "live_proj": team1_live_proj},
            team2_name: {"current_stats": team2_current_stats, "live_proj": team2_live_proj},
            "off_days": off_days
        })
    except Exception as e:
        print(f"An unexpected error in /api/matchup: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

@api_bp.route("/api/simulate-week", methods=['POST'])
def api_simulate_week():
    data = request.json
    my_team_name = data.get('my_team')
    opponent_name = data.get('opponent')
    transactions = data.get('transactions', [])
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)
    week_num = session.get('week_num')


    if not all([my_team_name, opponent_name, week_num, cached_data]):
        return jsonify({"error": "Missing required parameters or cached data"}), 400

    try:
        all_rosters = cached_data['rosters']
        my_roster = all_rosters.get(my_team_name)
        opponent_roster = all_rosters.get(opponent_name)
        if not my_roster or not opponent_roster:
            return jsonify({"error": "Team names not found"}), 404
        con = sqlite3.connect(config.DB_FILE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        week_dates = {'start': date.fromisoformat(week_info['start_date']), 'end': date.fromisoformat(week_info['end_date'])}

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row[0]: json.loads(row[1]) for row in cur.fetchall()}
        con.close()

        my_simulated_totals, daily_lineups, simulated_roster = calculate_optimized_totals(my_roster, week_num, schedules, week_dates, transactions)
        opponent_totals, _, _ = calculate_optimized_totals(opponent_roster, week_num, schedules, week_dates)

        utilization_roster = []
        for player in simulated_roster:
            starts = [day for day, lineup in daily_lineups.items() if player['name'] in [p['name'] for p, pos in lineup]]
            player_team = player.get('team', 'N/A')
            player_schedule = schedules.get(player_team, [])
            games_this_week = sum(1 for d_str in player_schedule if week_dates['start'] <= date.fromisoformat(d_str) <= week_dates['end'])

            player_data = {
                'name': player['name'],
                'positions': player.get('positions', ''),
                'games_this_week': games_this_week,
                'starts_this_week': len(starts),
                'start_days': ', '.join([datetime.fromisoformat(d).strftime('%a') for d in sorted(starts)])
            }
            utilization_roster.append(player_data)

        return jsonify({
            "simulated_matchup": {
                my_team_name: {"totals": my_simulated_totals},
                opponent_name: {"totals": opponent_totals}
            },
            "simulated_utilization": utilization_roster
        })
    except Exception as e:
        print(f"An unexpected error in /api/simulate-week: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

@api_bp.route("/api/optimizer")
def api_optimizer():
    my_team_name = request.args.get('my_team', type=str)
    opponent_name = request.args.get('opponent', type=str)
    target_date_str = request.args.get('date', type=str)
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)
    week_num = session.get('week_num')


    if not all([my_team_name, opponent_name, week_num, cached_data, target_date_str]):
        return jsonify({"error": "Missing required parameters or cached data"}), 400

    try:
        LEAGUE_CATEGORIES = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'ga']
        all_rosters = cached_data['rosters']
        my_roster = all_rosters.get(my_team_name)
        opponent_roster = all_rosters.get(opponent_name)
        if not my_roster or not opponent_roster:
            return jsonify({"error": "One or both team names not found"}), 404

        con = sqlite3.connect(config.DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        week_dates = {'start': date.fromisoformat(week_info[0]), 'end': date.fromisoformat(week_info[1])}

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row[0]: json.loads(row[1]) for row in cur.fetchall()}
        con.close()

        my_totals, _, _ = calculate_optimized_totals(my_roster, week_num, schedules, week_dates)
        opponent_totals, _, _ = calculate_optimized_totals(opponent_roster, week_num, schedules, week_dates)

        category_weights = {}
        inverse_stats = ['ga']

        for stat in LEAGUE_CATEGORIES:
            my_stat = my_totals.get(stat, 0)
            opp_stat = opponent_totals.get(stat, 0)
            diff = my_stat - opp_stat
            if stat in inverse_stats: diff = -diff

            if diff < -2: category_weights[stat] = 3.0
            elif diff < 0: category_weights[stat] = 2.0
            elif diff < 2: category_weights[stat] = 1.0
            else: category_weights[stat] = 0.5

        active_players = [p for p in my_roster if p.get('team') in schedules and target_date_str in schedules[p.get('team')]]

        optimal_roster, benched_players = find_optimal_lineup(active_players, category_weights)

        return jsonify({
            "optimal_roster": [p for p, pos in optimal_roster],
            "benched_players": benched_players,
            "date": target_date_str,
            "context": {
                "my_team_totals": my_totals,
                "opponent_totals": opponent_totals,
                "category_weights": category_weights
            }
        })

    except Exception as e:
        print(f"An unexpected error in /api/optimizer: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

@api_bp.route("/api/weekly-optimizer")
def api_weekly_optimizer():
    team_name = request.args.get('team', type=str)
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)
    week_num = session.get('week_num')

    if not all([team_name, week_num, cached_data]):
        return jsonify({"error": "Missing parameters or cached data"}), 400

    try:
        all_rosters = cached_data['rosters']
        team_roster = all_rosters.get(team_name)
        if not team_roster: return jsonify({"error": f"Team '{team_name}' not found"}), 404

        con = sqlite3.connect(config.DB_FILE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        start_date = datetime.fromisoformat(week_info['start_date']).date()
        end_date = datetime.fromisoformat(week_info['end_date']).date()

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row[0]: json.loads(row[1]) for row in cur.fetchall()}
        con.close()

        player_start_days = {player['name']: [] for player in team_roster}
        open_slots_by_day = {}

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            day_of_week = current_date.strftime('%a')

            active_today = [p for p in team_roster if p.get('team') in schedules and date_str in schedules[p.get('team')]]

            total_slots = {'C': 2, 'LW': 2, 'RW': 2, 'D': 4, 'G': 2}

            if active_today:
                optimal_roster_tuples, _ = find_optimal_lineup(active_today)
                for player, pos_filled in optimal_roster_tuples:
                    if player['name'] in player_start_days:
                        player_start_days[player['name']].append(day_of_week)
                    if pos_filled in total_slots:
                        total_slots[pos_filled] -= 1

            open_slots_by_day[day_of_week] = total_slots
            current_date += timedelta(days=1)

        utilization_roster = []
        for player in team_roster:
            player_data = player.copy()
            starts = player_start_days.get(player['name'], [])
            player_data['starts_this_week'] = len(starts)
            player_data['start_days'] = ', '.join(starts)

            # Add team game days
            player_team = player_data.get('team', 'N/A')
            team_schedule = schedules.get(player_team, [])
            team_game_days = [datetime.fromisoformat(d).strftime('%a') for d in team_schedule if start_date <= datetime.fromisoformat(d).date() <= end_date]
            player_data['team_game_days'] = ', '.join(sorted(list(set(team_game_days)), key=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].index))

            utilization_roster.append(player_data)

        return jsonify({
            "roster_utilization": utilization_roster,
            "open_slots": open_slots_by_day
            })

    except Exception as e:
        print(f"An unexpected error in /api/weekly-optimizer: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500


@api_bp.route("/api/free-agents")
def api_free_agents():
    my_team_name = request.args.get('my_team', type=str)
    opponent_name = request.args.get('opponent', type=str)
    start_index = request.args.get('start', type=int, default=0)
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)
    week_num = session.get('week_num')


    if not all([my_team_name, opponent_name, week_num, cached_data]):
        return jsonify({"error": "Missing required parameters or cached data"}), 400

    try:
        all_rosters = cached_data['rosters']
        evaluated_fas = cached_data['available_players']

        my_roster = all_rosters.get(my_team_name)
        opponent_roster = all_rosters.get(opponent_name)
        if not my_roster or not opponent_roster:
            return jsonify({"error": "Team names not found"}), 404

        con = sqlite3.connect(config.DB_FILE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        week_dates = {'start': date.fromisoformat(week_info['start_date']), 'end': date.fromisoformat(week_info['end_date'])}

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row['team_tricode']: json.loads(row['schedule_json']) for row in cur.fetchall()}

        my_totals, my_daily_lineups, _ = calculate_optimized_totals(my_roster, week_num, schedules, week_dates)
        opponent_totals, _, _ = calculate_optimized_totals(opponent_roster, week_num, schedules, week_dates)

        LEAGUE_CATEGORIES = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'ga']
        category_weights = {}
        for stat in LEAGUE_CATEGORIES:
            my_stat, opp_stat = my_totals.get(stat, 0), opponent_totals.get(stat, 0)
            diff = my_stat - opp_stat
            if stat == 'ga': diff = -diff
            if diff < -2: category_weights[stat] = 3.0
            elif diff < 0: category_weights[stat] = 2.0
            elif diff < 2: category_weights[stat] = 1.0
            else: category_weights[stat] = 0.5

        my_player_values = []
        droppable_skaters = [ p for p in my_roster if 'G' not in p.get('positions', '') and 'IR' not in p.get('positions', '') and 'IR+' not in p.get('positions', '')]

        for p in droppable_skaters:
            starts = sum(1 for lineup in my_daily_lineups.values() if p['name'] in [player['name'] for player, pos in lineup])
            value = 0
            for stat, weight in category_weights.items():
                try: stat_val = float(p['per_game_projections'].get(stat, 0.0))
                except (ValueError, TypeError): stat_val = 0.0
                value += (stat_val * weight if stat != 'ga' else -stat_val * weight) * starts
            my_player_values.append({'name': p['name'], 'value': value})

        ideal_drop = min(my_player_values, key=lambda x: x['value']) if my_player_values else None

        # The free agents are already enriched from the cache, we just need to calculate their value
        for fa_data in evaluated_fas:
            fa_data['weekly_impact_score'] = 0 # Reset score
            fa_proj = fa_data.get('per_game_projections', {})

            current_date = week_dates['start']
            while current_date <= week_dates['end']:
                date_str = current_date.isoformat()
                if fa_data['team'] in schedules and date_str in schedules[fa_data['team']]:
                    my_optimal_today = [p for p, pos in my_daily_lineups.get(date_str, [])]
                    roster_with_fa = my_optimal_today + [fa_data]
                    optimal_lineup_with_fa, _ = find_optimal_lineup(roster_with_fa, category_weights)

                    if any(p['name'] == fa_data['name'] for p, pos in optimal_lineup_with_fa):
                        value = 0
                        for stat, weight in category_weights.items():
                            try: stat_val = float(fa_proj.get(stat, 0.0))
                            except (ValueError, TypeError): stat_val = 0.0
                            value += (stat_val * weight) if stat != 'ga' else -(stat_val * weight)
                        fa_data['weekly_impact_score'] += value
                current_date += timedelta(days=1)

            fa_data['suggested_drop'] = ideal_drop['name'] if ideal_drop else "N/A"

        con.close()

        evaluated_fas.sort(key=lambda x: x['weekly_impact_score'], reverse=True)
        paginated_results = evaluated_fas[start_index : start_index + 20]

        return jsonify({
            "free_agents": paginated_results,
            "context": {"category_weights": category_weights}
        })

    except Exception as e:
        print(f"An unexpected error in /api/free-agents: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

@api_bp.route("/api/goalie-scenarios")
def api_goalie_scenarios():
    team_name = request.args.get('team', type=str)
    starts = request.args.get('starts', type=int, default=1)
    cache_key = session.get('cache_key')
    cached_data = LEAGUE_DATA_CACHE.get(cache_key)

    if not all([team_name, cached_data]):
        return jsonify({"error": "Missing parameters or cached data"}), 400

    try:
        live_stats = cached_data['live_stats'].get(team_name, {})

        try:
            current_ga = float(live_stats.get('ga', 0))
            current_sv = float(live_stats.get('sv', 0))
            svpct = float(live_stats.get('svpct', 0))
            current_gaa = float(live_stats.get('gaa', 0.0))
        except (ValueError, TypeError):
             # Handle cases where stats might not be numbers yet (e.g., at week start)
            current_ga, current_sv, svpct, current_gaa = 0.0, 0.0, 0.0, 0.0

        current_shots_against = current_sv / svpct if svpct > 0 else 0


        scenarios_def = [
            {"name": "Excellent Start", "ga": 1, "svpct": 0.960},
            {"name": "Good Start", "ga": 2, "svpct": 0.925},
            {"name": "Average Start", "ga": 3, "svpct": 0.900},
            {"name": "Bad Start", "ga": 4, "svpct": 0.850},
            {"name": "Disaster Start", "ga": 5, "svpct": 0.800},
        ]

        results = []
        for scenario in scenarios_def:
            hypo_shots = 30 * starts
            hypo_sv = hypo_shots * scenario["svpct"]

            new_total_sv = current_sv + hypo_sv
            new_total_shots = current_shots_against + hypo_shots
            new_svpct = new_total_sv / new_total_shots if new_total_shots > 0 else 0

            # This part of the logic remains a bit abstract as we don't know live games started
            # We will just show the resulting SV% as GAA would be a guess.
            results.append({
                "name": f"{starts} {scenario['name']}(s)",
                "gaa": "N/A", # GAA is too complex to predict without knowing GS
                "svpct": new_svpct
            })

        return jsonify({
            "current_gaa": current_gaa,
            "current_svpct": svpct,
            "scenarios": results
        })

    except Exception as e:
        print(f"An unexpected error in /api/goalie-scenarios: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500
