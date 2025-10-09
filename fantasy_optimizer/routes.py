"""
This module contains all the Flask routes (API endpoints) for the application.
It uses a Flask Blueprint to keep the routes organized and separate from the main
application initialization logic.
"""
import sqlite3
import json
import time
import re
import unicodedata
from datetime import date, timedelta, datetime
from flask import Blueprint, jsonify, request, send_from_directory, session
from yahoo_fantasy_api import game
from . import config
from .auth import get_oauth_client
from .data_helpers import get_user_leagues, get_weekly_roster_data, calculate_optimized_totals, get_live_stats_for_team, normalize_name, get_healthy_free_agents
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
    """
    Serves the main index.html file from the project's root directory.
    We go 'up' one level from the current blueprint's directory.
    """
    return send_from_directory('..', 'index.html')

@api_bp.route('/players.html')
def players_page():
    """Serves the new players.html file."""
    return send_from_directory('..', 'players.html')


# --- API Routes ---

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
    """API endpoint to get raw roster data for a specific week and league."""
    league_id = request.args.get('league_id', type=str)

    if not week_num or not league_id:
        return jsonify({"error": "Missing week or league_id parameter"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    print(f"API endpoint hit for week {week_num}, league {league_id}. Fetching data...")
    try:
        rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in rosters:
            return jsonify(rosters), 500
        return jsonify(rosters)
    except Exception as e:
        print(f"Error in /api/rosters: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

@api_bp.route("/api/all-players")
def api_get_all_players():
    """
    API endpoint to get a team's roster and all available players (FA/W)
    for a given league and week, enriched with projection data.
    """
    league_id = request.args.get('league_id', type=str)
    team_name = request.args.get('team_name', type=str)
    week_num = request.args.get('week', type=int)

    if not all([league_id, team_name, week_num]):
        return jsonify({"error": "Missing required parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        # 1. Get all roster data, which includes the specific team's roster
        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters:
            return jsonify(all_rosters), 500
        team_roster = all_rosters.get(team_name)
        if not team_roster:
            return jsonify({"error": f"Team '{team_name}' not found."}), 404

        # 2. Get all available players from Yahoo
        lg = gm.to_league(league_id)
        available_players_raw = get_healthy_free_agents(lg)

        # 3. Connect to DB to enrich player data
        con = sqlite3.connect(config.DB_FILE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        week_start = date.fromisoformat(week_info['start_date'])
        week_end = date.fromisoformat(week_info['end_date'])

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row['team_tricode']: json.loads(row['schedule_json']) for row in cur.fetchall()}

        # 4. Process the raw available players list to add projections
        processed_available_players = []
        for player in available_players_raw:
            normalized_name = normalize_name(player['name'])

            if normalized_name in ['sebastianaho', 'eliaspettersson']:
                is_forward = any(pos in ['C', 'LW', 'RW', 'F'] for pos in player['eligible_positions'])
                is_defense = 'D' in player['eligible_positions']
                if is_forward and not is_defense: normalized_name = f"{normalized_name}f"
                elif is_defense and not is_forward: normalized_name = f"{normalized_name}d"

            cur.execute("SELECT * FROM projections WHERE normalized_name = ?", (normalized_name,))
            proj_row = cur.fetchone()
            if not proj_row:
                continue

            proj_dict = dict(proj_row)
            team_tricode = proj_dict.get('team', 'N/A').upper()
            schedule = schedules.get(team_tricode, [])
            games_this_week = sum(1 for d_str in schedule if week_start <= date.fromisoformat(d_str) <= week_end)

            weekly_projections = {}
            for stat, value in proj_dict.items():
                if isinstance(value, (int, float)):
                    if stat in ['gaa', 'svpct']:
                        weekly_projections[stat] = float(value)
                    else:
                        weekly_projections[stat] = round(float(value) * games_this_week, 2)

            processed_player = {
                "name": player['name'],
                "team": team_tricode,
                "availability": player.get('availability', 'FA'),
                "positions": ', '.join(player['eligible_positions']),
                "games_this_week": games_this_week,
                "weekly_projections": weekly_projections,
                "per_game_projections": proj_dict
            }
            processed_available_players.append(processed_player)

        con.close()

        return jsonify({
            "team_roster": team_roster,
            "available_players": processed_available_players
        })

    except Exception as e:
        if 'con' in locals() and con:
            con.close()
        print(f"An unexpected error in /api/all-players: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500


@api_bp.route("/api/matchup")
def api_get_matchup():
    week_num = request.args.get('week', type=int)
    league_id = request.args.get('league_id', type=str)
    team1_name = request.args.get('team1', type=str)
    team2_name = request.args.get('team2', type=str)

    if not all([week_num, league_id, team1_name, team2_name]):
        return jsonify({"error": "Missing required parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        lg = gm.to_league(league_id)
        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500

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

        team1_live_stats = get_live_stats_for_team(lg, team1_name, week_num)
        team2_live_stats = get_live_stats_for_team(lg, team2_name, week_num)

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
                # Skip rate stats and raw stats used for calculation
                if key in ['svpct', 'gaa'] or key.startswith('raw_'):
                    continue
                try:
                    # Ensure both operands are numbers before adding
                    live_val = float(live.get(key, 0))
                    rem_val = float(remainder.get(key, 0))
                    combined[key] = live_val + rem_val
                except (ValueError, TypeError):
                    # Fallback if a value isn't a number
                    combined[key] = remainder.get(key, 0)

            # --- Recalculate Goalie Rate Stats ---
            # FIX: Prioritize using actual live SA and GS if available from the API,
            # falling back to approximation only if necessary.
            live_ga = float(live.get('ga', 0))
            live_sv = float(live.get('sv', 0))
            live_sa = float(live.get('sa', 0))
            live_gs = float(live.get('gs', 0))

            # Fallback approximation for older API responses that might lack SA/GS
            if live_sa == 0:
                try:
                    live_svpct = float(live.get('svpct', 0))
                    if live_svpct > 0:
                        live_sa = live_sv / live_svpct
                except (ValueError, TypeError, ZeroDivisionError):
                    live_sa = 0

            if live_gs == 0:
                try:
                    live_gaa = float(live.get('gaa', 0))
                    if live_gaa > 0:
                        live_gs = live_ga / live_gaa
                except (ValueError, TypeError, ZeroDivisionError):
                    live_gs = 0

            rem_ga = remainder.get('raw_ga', 0)
            rem_sv = remainder.get('raw_sv', 0)
            rem_sa = remainder.get('raw_sa', 0)
            rem_gs = remainder.get('raw_gs', 0)

            total_ga = live_ga + rem_ga
            total_sv = live_sv + rem_sv
            total_sa = live_sa + rem_sa
            total_gs = live_gs + rem_gs

            # Update combined dictionary with correctly calculated rate stats
            combined['gaa'] = round(total_ga / total_gs, 3) if total_gs > 0 else 0.0
            combined['svpct'] = round(total_sv / total_sa, 3) if total_sa > 0 else 0.0

            # Round other stats for cleaner display
            for key, value in combined.items():
                if key not in ['svpct', 'gaa']:
                    combined[key] = round(value, 2)

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
    week_num = data.get('week')
    league_id = data.get('league_id')
    my_team_name = data.get('my_team')
    opponent_name = data.get('opponent')
    transactions = data.get('transactions', [])

    if not all([week_num, league_id, my_team_name, opponent_name]):
        return jsonify({"error": "Missing required parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500

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
    week_num = request.args.get('week', type=int)
    league_id = request.args.get('league_id', type=str)
    target_date_str = request.args.get('date', type=str)

    if not all([my_team_name, opponent_name, week_num, league_id, target_date_str]):
        return jsonify({"error": "Missing required parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        LEAGUE_CATEGORIES = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'ga']

        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500

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
    week_num = request.args.get('week', type=int)
    league_id = request.args.get('league_id', type=str)

    if not all([team_name, week_num, league_id]):
        return jsonify({"error": "Missing parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500
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
        schedules = {row['team_tricode']: json.loads(row['schedule_json']) for row in cur.fetchall()}
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
    week_num = request.args.get('week', type=int)
    league_id = request.args.get('league_id', type=str)
    start_index = request.args.get('start', type=int, default=0)

    if not all([my_team_name, opponent_name, week_num, league_id]):
        return jsonify({"error": "Missing required parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        lg = gm.to_league(league_id)
        all_rosters = get_weekly_roster_data(gm, league_id, week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500
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

        healthy_free_agents = get_healthy_free_agents(lg)

        evaluated_fas = []
        for fa in healthy_free_agents:
            try:
                normalized_fa_name = normalize_name(fa['name'])
                if normalized_fa_name in ['sebastianaho', 'eliaspettersson']:
                    is_forward = any(pos in ['C', 'LW', 'RW', 'F'] for pos in fa['eligible_positions'])
                    is_defense = 'D' in fa['eligible_positions']
                    if is_forward and not is_defense:
                        normalized_fa_name = f"{normalized_fa_name}f"
                    elif is_defense and not is_forward:
                        normalized_fa_name = f"{normalized_fa_name}d"

                cur.execute("SELECT * FROM projections WHERE normalized_name = ?", (normalized_fa_name,))
                fa_proj_row = cur.fetchone()
                if not fa_proj_row: continue
                fa_proj = dict(fa_proj_row)

                fa_team = fa_proj.get('team', 'N/A').upper()
                fa_schedule = schedules.get(fa_team, [])
                games_this_week = sum(1 for d_str in fa_schedule if week_dates['start'] <= date.fromisoformat(d_str) <= week_dates['end'])
                if games_this_week == 0: continue

                fa_data = { "name": fa['name'], "positions": ', '.join(fa['eligible_positions']), "team": fa_team, "per_game_projections": fa_proj, "weekly_impact_score": 0, "games_this_week": games_this_week, "start_days": [], "weekly_projections": {}, "availability": fa.get('availability', 'FA')}

                for stat, value in fa_proj.items():
                    if stat not in ['player_name', 'team', 'positions'] and value is not None:
                        try: fa_data['weekly_projections'][stat] = round(float(value) * games_this_week, 2)
                        except (ValueError, TypeError): continue

                current_date = week_dates['start']
                while current_date <= week_dates['end']:
                    date_str = current_date.isoformat()
                    if date_str in fa_schedule:
                        my_optimal_today = [p for p, pos in my_daily_lineups.get(date_str, [])]
                        roster_with_fa = my_optimal_today + [fa_data]
                        optimal_lineup_with_fa, _ = find_optimal_lineup(roster_with_fa, category_weights)

                        if any(p['name'] == fa_data['name'] for p, pos in optimal_lineup_with_fa):
                            fa_data['start_days'].append(current_date.strftime('%a'))
                            value = 0
                            for stat, weight in category_weights.items():
                                try: stat_val = float(fa_proj.get(stat, 0.0))
                                except (ValueError, TypeError): stat_val = 0.0
                                value += (stat_val * weight) if stat != 'ga' else -(stat_val * weight)
                            fa_data['weekly_impact_score'] += value
                    current_date += timedelta(days=1)

                if fa_data['weekly_impact_score'] > 0:
                    fa_data['suggested_drop'] = ideal_drop['name'] if ideal_drop else "N/A"
                    fa_data['start_days'] = ', '.join(fa_data['start_days'])
                    evaluated_fas.append(fa_data)

            except (KeyError, TypeError, ValueError) as e:
                print(f"Skipping FA {fa.get('name', 'Unknown')}. Error: {e}")
                continue

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
    week_num = request.args.get('week', type=int)
    league_id = request.args.get('league_id', type=str)
    starts = request.args.get('starts', type=int, default=1)

    if not all([team_name, week_num, league_id]):
        return jsonify({"error": "Missing parameters"}), 400

    gm, error = check_auth_and_get_game()
    if error:
        return error

    try:
        lg = gm.to_league(league_id)
        live_stats = get_live_stats_for_team(lg, team_name, week_num)

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
