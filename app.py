"""
Fantasy Hockey Matchup Optimizer

Author: Jason Druckenmiller
Date Created: 09/08/2025
Last Updated: 09/09/2055
"""
# app.py

import os
import sqlite3
import json
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_httpauth import HTTPBasicAuth
import yahoo_fantasy_api as yfa
from yahoo_oauth import OAuth2
from io import StringIO

# --- App Initialization & Config ---
app = Flask(__name__)
CORS(app)
auth = HTTPBasicAuth()

# --- NEW: Set your desired username and password here for the live app ---
users = {
    "your_username": "your_password",
    "1": "1"
}
# --------------------------------------------------------------------

DB_FILE = "projections.db"
YAHOO_LEAGUE_KEY = '453.l.2200'

private_content = os.environ.get('YAHOO_PRIVATE_JSON')
if private_content:
    print("Loading Yahoo credentials from environment variable.")
    YAHOO_CREDENTIALS_FILE = StringIO(private_content)
else:
    print("Loading Yahoo credentials from local private.json file.")
    YAHOO_CREDENTIALS_FILE = 'private.json'

@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username

# --- NEW: Routes to serve the frontend files ---
@app.route('/')
@auth.login_required
def index():
    return send_from_directory('.', 'index.html')

@app.route('/app.js')
@auth.login_required
def js():
    return send_from_directory('.', 'app.js')
# -----------------------------------------------

# --- HELPER: Core Optimization Logic ---
def find_optimal_lineup(active_players, category_weights={}):
    # ... (this function remains the same)
    def safe_get_stat(player, stat_name):
        try:
            proj = player.get('per_game_projections', {})
            return float(proj.get(stat_name, 0))
        except (ValueError, TypeError): return 0

    def calculate_marginal_value(player, weights):
        if not weights: return safe_get_stat(player, 'pts')
        value = 0
        inverse_stats = ['ga']
        for stat, weight in weights.items():
            player_stat = safe_get_stat(player, stat)
            value += -player_stat * weight if stat in inverse_stats else player_stat * weight
        return value

    ir_players = [p for p in active_players if 'IR' in p.get('positions', '') or 'IR+' in p.get('positions', '')]
    eligible_players = [p for p in active_players if p not in ir_players]

    for p in eligible_players:
        p['marginal_value'] = calculate_marginal_value(p, category_weights)

    eligible_skaters = [p for p in eligible_players if 'G' not in p.get('positions', '').split(', ')]
    eligible_goalies = [p for p in eligible_players if 'G' in p.get('positions', '').split(', ')]

    eligible_goalies.sort(key=lambda p: safe_get_stat(p, 'w'), reverse=True)
    optimal_goalies = [(g, 'G') for g in eligible_goalies[:2]]
    benched_goalies = eligible_goalies[2:]

    eligible_skaters.sort(key=lambda p: p.get('marginal_value', 0), reverse=True)

    memo = {}
    ordered_skater_slots = ['C', 'LW', 'RW', 'D']

    def solve_skaters(player_index, slots_tuple):
        if player_index == len(eligible_skaters): return 0, []
        state = (player_index, slots_tuple)
        if state in memo: return memo[state]

        slots = dict(zip(ordered_skater_slots, slots_tuple))
        player = eligible_skaters[player_index]
        best_score, best_lineup = solve_skaters(player_index + 1, slots_tuple)

        player_positions = [p for p in player.get('positions', '').split(', ') if p in slots]
        for pos in player_positions:
            if slots[pos] > 0:
                new_slots = slots.copy(); new_slots[pos] -= 1
                path_score, path_lineup = solve_skaters(player_index + 1, tuple(new_slots.values()))
                current_score = player.get('marginal_value', 0) + path_score

                if current_score > best_score:
                    best_score, best_lineup = current_score, [(player, pos)] + path_lineup

        memo[state] = (best_score, best_lineup)
        return best_score, best_lineup

    initial_skater_slots = {'C': 2, 'LW': 2, 'RW': 2, 'D': 4}
    _, optimal_skaters = solve_skaters(0, tuple(initial_skater_slots[s] for s in ordered_skater_slots))

    optimal_roster = optimal_skaters + optimal_goalies

    optimal_player_names = {p['name'] for p, pos in optimal_roster}
    benched_skaters = [p for p in eligible_skaters if p['name'] not in optimal_player_names]
    benched_players = benched_skaters + benched_goalies + ir_players

    return optimal_roster, benched_players

def get_weekly_roster_data(week_num):
    # ... (this function remains the same as the previous version)
    # --- 1. Connect to DB and get week start/end dates ---
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
    week_info = cur.fetchone()
    if not week_info:
        return {"error": f"Fantasy week {week_num} not found in the database."}

    week_start_date = datetime.fromisoformat(week_info['start_date']).date()
    week_end_date = datetime.fromisoformat(week_info['end_date']).date()

    # --- 2. Get games per team for the specified week ---
    games_this_week = {}
    cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
    all_schedules = cur.fetchall()
    for row in all_schedules:
        team_tricode = row['team_tricode']
        schedule_dates = json.loads(row['schedule_json'])
        game_count = 0
        for date_str in schedule_dates:
            game_date = datetime.fromisoformat(date_str).date()
            if week_start_date <= game_date <= week_end_date:
                game_count += 1
        games_this_week[team_tricode] = game_count

    # --- 3. Fetch Yahoo Fantasy Rosters ---
    if not os.path.exists('private.json') and not private_content:
         return {"error": "Yahoo credentials not found"}

    try:
        oauth = OAuth2(None, None, from_file=YAHOO_CREDENTIALS_FILE)
        if not oauth.token_is_valid(): oauth.refresh_access_token()

        game = yfa.Game(oauth, 'nhl')
        lg = game.to_league(YAHOO_LEAGUE_KEY)
        all_rosters = {}
        all_teams_data = lg.teams()

        # --- 4. Combine all data for each player ---
        for team_key, team_info in all_teams_data.items():
            team_name = team_info['name']
            team = lg.to_team(team_key)
            roster = team.roster()
            roster_data = []

            for player in roster:
                cur.execute("SELECT * FROM projections WHERE player_name = ?", (player['name'],))
                projection_row = cur.fetchone()

                player_projections = dict(projection_row) if projection_row else {}
                player_team_tricode = player_projections.get('team', 'N/A').upper() if player_projections else 'N/A'

                # Calculate weekly stats
                weekly_projections = {}
                num_games = games_this_week.get(player_team_tricode, 0)
                for stat, value in player_projections.items():
                    if stat not in ['player_name', 'team'] and value is not None:
                        try:
                            numeric_value = float(value)
                            weekly_stat = round(numeric_value * num_games, 2)
                            weekly_projections[stat] = weekly_stat
                        except (ValueError, TypeError):
                            continue

                player_data = {
                    "name": player['name'],
                    "positions": ', '.join(player['eligible_positions']),
                    "team": player_team_tricode,
                    "status": player.get('status', 'OK'),
                    "games_this_week": num_games,
                    "weekly_projections": weekly_projections,
                    "per_game_projections": player_projections
                }
                roster_data.append(player_data)

            all_rosters[team_name] = roster_data

        con.close()
        return all_rosters

    except Exception as e:
        con.close()
        return {"error": f"An error occurred: {e}"}


@app.route("/api/rosters/week/<int:week_num>")
@auth.login_required
def api_get_rosters_for_week(week_num):
    print(f"API endpoint hit for week {week_num}. Fetching data...")
    rosters = get_weekly_roster_data(week_num)
    return jsonify(rosters)

def calculate_optimized_totals(roster, week_num, schedules, week_dates, transactions=[]):
    # ... (this function remains the same)
    totals = {}
    daily_lineups = {}
    goalie_avg_stats = ['svpct', 'ga']
    goalie_stat_numerator = {stat: 0 for stat in goalie_avg_stats}
    total_goalie_starts = 0

    simulated_roster = list(roster)
    transactions.sort(key=lambda x: x['date'])
    trans_index = 0

    current_date = week_dates['start']
    while current_date <= week_dates['end']:
        date_str = current_date.isoformat()

        while trans_index < len(transactions) and transactions[trans_index]['date'] == date_str:
            move = transactions[trans_index]
            simulated_roster = [p for p in simulated_roster if p['name'] != move['drop']]
            con = sqlite3.connect(DB_FILE)
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT * FROM projections WHERE player_name = ?", (move['add'],))
            new_player_proj = cur.fetchone()
            con.close()
            if new_player_proj:
                new_player_data = {
                    'name': move['add'],
                    'positions': new_player_proj['positions'] or '',
                    'team': new_player_proj['team'],
                    'per_game_projections': dict(new_player_proj)
                }
                simulated_roster.append(new_player_data)
            trans_index += 1

        active_today = [p for p in simulated_roster if p.get('team') in schedules and date_str in schedules[p.get('team')]]

        optimal_roster_tuples = []
        if active_today:
            optimal_roster_tuples, _ = find_optimal_lineup(active_today)
            daily_lineups[date_str] = optimal_roster_tuples

            for player, pos_filled in optimal_roster_tuples:
                for stat, value in player['per_game_projections'].items():
                    if stat in ['player_name', 'team']: continue
                    try:
                        numeric_value = float(value)
                        if 'G' in player.get('positions', '') and stat in goalie_avg_stats:
                            goalie_stat_numerator[stat] += numeric_value
                        else:
                            totals[stat] = totals.get(stat, 0) + numeric_value
                    except (ValueError, TypeError): continue
                if 'G' in player.get('positions', ''):
                    total_goalie_starts += 1
        current_date += timedelta(days=1)

    for stat in goalie_avg_stats:
        totals[stat] = (goalie_stat_numerator[stat] / total_goalie_starts) if total_goalie_starts > 0 else 0

    for stat, value in totals.items():
        totals[stat] = round(value, 3 if stat == 'svpct' else 2)
    return totals, daily_lineups, simulated_roster

@app.route("/api/matchup")
@auth.login_required
def api_get_matchup():
    # ... (this function remains the same)
    week_num = request.args.get('week', type=int)
    team1_name = request.args.get('team1', type=str)
    team2_name = request.args.get('team2', type=str)

    if not all([week_num, team1_name, team2_name]):
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        all_rosters = get_weekly_roster_data(week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500

        team1_roster = all_rosters.get(team1_name)
        team2_roster = all_rosters.get(team2_name)
        if not team1_roster or not team2_roster:
            return jsonify({"error": "One or both team names not found"}), 404

        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        full_week_dates = {'start': date.fromisoformat(week_info[0]), 'end': date.fromisoformat(week_info[1])}

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row[0]: json.loads(row[1]) for row in cur.fetchall()}

        cur.execute("SELECT off_day_date FROM off_days WHERE off_day_date >= ? AND off_day_date <= ?", (full_week_dates['start'].isoformat(), full_week_dates['end'].isoformat()))
        off_days = [row[0] for row in cur.fetchall()]
        con.close()

        team1_full_proj, _, _ = calculate_optimized_totals(team1_roster, week_num, schedules, full_week_dates)
        team2_full_proj, _, _ = calculate_optimized_totals(team2_roster, week_num, schedules, full_week_dates)

        oauth = OAuth2(None, None, from_file=YAHOO_CREDENTIALS_FILE)
        if not oauth.token_is_valid(): oauth.refresh_access_token()
        game = yfa.Game(oauth, 'nhl')
        lg = game.to_league(YAHOO_LEAGUE_KEY)

        team_keys = {t['name']: t['team_key'] for t in lg.teams().values()}

        team1_live_stats = {}
        team2_live_stats = {}
        try:
            matchup_data = lg.matchup(week_num)
            team1_live_stats = matchup_data['teams'][team_keys[team1_name]]['stats']
            team2_live_stats = matchup_data['teams'][team_keys[team2_name]]['stats']
        except Exception as e:
             print(f"Could not fetch live matchup data (this is expected for past/future weeks): {e}")


        today = date.today()
        remainder_start = max(today, full_week_dates['start'])
        remainder_week_dates = {'start': remainder_start, 'end': full_week_dates['end']}

        team1_remainder, _, _ = calculate_optimized_totals(team1_roster, week_num, schedules, remainder_week_dates)
        team2_remainder, _, _ = calculate_optimized_totals(team2_roster, week_num, schedules, remainder_week_dates)

        def combine_stats(live, remainder):
            combined = {}
            all_keys = set(live.keys()) | set(remainder.keys())
            for key in all_keys:
                try:
                    combined[key] = float(live.get(key, 0)) + remainder.get(key, 0)
                except (ValueError, TypeError):
                    combined[key] = remainder.get(key, 0)

            if 'svpct' in live: combined['svpct'] = float(live.get('svpct', 0))
            if 'ga' in live: combined['ga'] = float(live.get('ga', 0))
            return combined

        team1_live_proj = combine_stats(team1_live_stats, team1_remainder)
        team2_live_proj = combine_stats(team2_live_stats, team2_remainder)

        return jsonify({
            team1_name: {"full_week_proj": team1_full_proj, "live_proj": team1_live_proj},
            team2_name: {"full_week_proj": team2_full_proj, "live_proj": team2_live_proj},
            "off_days": off_days
        })
    except Exception as e:
        print(f"An unexpected error in /api/matchup: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

@app.route("/api/simulate-week", methods=['POST'])
@auth.login_required
def api_simulate_week():
    # ... (this function remains the same)
    data = request.json
    week_num = data.get('week')
    my_team_name = data.get('my_team')
    opponent_name = data.get('opponent')
    transactions = data.get('transactions', [])

    if not all([week_num, my_team_name, opponent_name]):
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        all_rosters = get_weekly_roster_data(week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500

        my_roster = all_rosters.get(my_team_name)
        opponent_roster = all_rosters.get(opponent_name)
        if not my_roster or not opponent_roster:
            return jsonify({"error": "Team names not found"}), 404

        con = sqlite3.connect(DB_FILE)
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

@app.route("/api/optimizer")
@auth.login_required
def api_optimizer():
    # ... (this function remains the same)
    my_team_name = request.args.get('my_team', type=str)
    opponent_name = request.args.get('opponent', type=str)
    week_num = request.args.get('week', type=int)
    target_date_str = request.args.get('date', type=str)

    if not all([my_team_name, opponent_name, week_num, target_date_str]):
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        LEAGUE_CATEGORIES = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'ga']

        all_rosters = get_weekly_roster_data(week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500

        my_roster = all_rosters.get(my_team_name)
        opponent_roster = all_rosters.get(opponent_name)
        if not my_roster or not opponent_roster:
            return jsonify({"error": "One or both team names not found"}), 404

        con = sqlite3.connect(DB_FILE)
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

@app.route("/api/weekly-optimizer")
@auth.login_required
def api_weekly_optimizer():
    # ... (this function remains the same)
    team_name = request.args.get('team', type=str)
    week_num = request.args.get('week', type=int)

    if not all([team_name, week_num]):
        return jsonify({"error": "Missing parameters: team and week"}), 400

    try:
        all_rosters = get_weekly_roster_data(week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500
        team_roster = all_rosters.get(team_name)
        if not team_roster: return jsonify({"error": f"Team '{team_name}' not found"}), 404

        con = sqlite3.connect(DB_FILE)
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
            utilization_roster.append(player_data)

        return jsonify({
            "roster_utilization": utilization_roster,
            "open_slots": open_slots_by_day
            })

    except Exception as e:
        print(f"An unexpected error in /api/weekly-optimizer: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500

# --- Free Agent Finder using Database as Source of Truth ---
@app.route("/api/free-agents")
@auth.login_required
def api_free_agents():
    # ... (this function remains the same)
    my_team_name = request.args.get('my_team', type=str)
    opponent_name = request.args.get('opponent', type=str)
    week_num = request.args.get('week', type=int)
    start_index = request.args.get('start', type=int, default=0)

    if not all([my_team_name, opponent_name, week_num]):
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        all_rosters = get_weekly_roster_data(week_num)
        if "error" in all_rosters: return jsonify(all_rosters), 500
        my_roster = all_rosters.get(my_team_name)
        opponent_roster = all_rosters.get(opponent_name)
        if not my_roster or not opponent_roster:
            return jsonify({"error": "Team names not found"}), 404

        rostered_player_names = {p['name'] for r in all_rosters.values() for p in r}

        con = sqlite3.connect(DB_FILE)
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

        cur.execute("SELECT * FROM projections")
        all_db_players = cur.fetchall()

        simulated_free_agents = [dict(p) for p in all_db_players if p['player_name'] not in rostered_player_names]

        evaluated_fas = []
        for fa_proj in simulated_free_agents:
            try:
                fa_team = fa_proj.get('team', 'N/A').upper()
                fa_schedule = schedules.get(fa_team, [])
                games_this_week = sum(1 for d_str in fa_schedule if week_dates['start'] <= date.fromisoformat(d_str) <= week_dates['end'])
                if games_this_week == 0: continue

                fa_data = { "name": fa_proj['player_name'], "positions": fa_proj.get('positions', ''), "team": fa_team, "per_game_projections": fa_proj, "weekly_impact_score": 0, "games_this_week": games_this_week, "start_days": [], "weekly_projections": {} }

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
                print(f"Skipping FA {fa_proj.get('player_name', 'Unknown')}. Error: {e}")
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

if __name__ == '__main__':
    app.run(debug=True)
