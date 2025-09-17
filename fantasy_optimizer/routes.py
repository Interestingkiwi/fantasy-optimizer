"""
This module contains all the Flask routes (API endpoints) for the application.
It uses a Flask Blueprint to keep the routes organized and separate from the main
application initialization logic.
"""
import sqlite3
import json
from datetime import date, timedelta, datetime
from flask import Blueprint, jsonify, request, send_from_directory

from . import config
from .auth import auth
from .data_helpers import get_weekly_roster_data, calculate_optimized_totals, get_live_stats_for_team
from .optimization_logic import find_optimal_lineup

# Create a Blueprint. This is Flask's way of organizing groups of related routes.
api_bp = Blueprint('api', __name__)

# --- Route to serve the main HTML file ---
@api_bp.route('/')
@auth.login_required
def index():
    """
    Serves the main index.html file from the project's root directory.
    We go 'up' one level from the current blueprint's directory.
    """
    return send_from_directory('..', 'index.html')

# --- API Routes ---

@api_bp.route("/api/rosters/week/<int:week_num>")
@auth.login_required
def api_get_rosters_for_week(week_num):
    """API endpoint to get raw roster data for a specific week."""
    print(f"API endpoint hit for week {week_num}. Fetching data...")
    rosters = get_weekly_roster_data(week_num)
    return jsonify(rosters)

@api_bp.route("/api/matchup")
@auth.login_required
def api_get_matchup():
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

        team1_full_proj, _, _ = calculate_optimized_totals(team1_roster, week_num, schedules, full_week_dates)
        team2_full_proj, _, _ = calculate_optimized_totals(team2_roster, week_num, schedules, full_week_dates)

        team1_live_stats = get_live_stats_for_team(team1_name, week_num)
        team2_live_stats = get_live_stats_for_team(team2_name, week_num)

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

@api_bp.route("/api/simulate-week", methods=['POST'])
@auth.login_required
def api_simulate_week():
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
@auth.login_required
def api_optimizer():
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
@auth.login_required
def api_weekly_optimizer():
    team_name = request.args.get('team', type=str)
    week_num = request.args.get('week', type=int)

    if not all([team_name, week_num]):
        return jsonify({"error": "Missing parameters: team and week"}), 400

    try:
        all_rosters = get_weekly_roster_data(week_num)
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


@api_bp.route("/api/free-agents")
@auth.login_required
def api_free_agents():
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

@api_bp.route("/api/goalie-scenarios")
@auth.login_required
def api_goalie_scenarios():
    team_name = request.args.get('team', type=str)
    week_num = request.args.get('week', type=int)
    starts = request.args.get('starts', type=int, default=1)

    if not all([team_name, week_num]):
        return jsonify({"error": "Missing team and week parameters"}), 400

    try:
        live_stats = get_live_stats_for_team(team_name, week_num)

        # Extract current totals to simulate against.
        current_ga = float(live_stats.get('ga', 0))
        current_sv = float(live_stats.get('sv', 0))
        # GS isn't a stat from Yahoo, so we have to derive shots against
        # total_shots = saves / save_percentage if svpct is not 0
        svpct = float(live_stats.get('svpct', 0))
        current_shots_against = current_sv / svpct if svpct > 0 else 0

        # Calculate current GAA. Yahoo provides this directly.
        current_gaa = float(live_stats.get('gaa', 0.0))

        # Define hypothetical scenarios for future starts
        scenarios_def = [
            {"name": "Excellent Start", "ga": 1, "svpct": 0.960},
            {"name": "Good Start", "ga": 2, "svpct": 0.925},
            {"name": "Average Start", "ga": 3, "svpct": 0.900},
            {"name": "Bad Start", "ga": 4, "svpct": 0.850},
            {"name": "Disaster Start", "ga": 5, "svpct": 0.800},
        ]

        results = []
        for scenario in scenarios_def:
            # Assume an average of 30 shots per game for hypotheticals
            hypo_shots = 30 * starts
            hypo_sv = hypo_shots * scenario["svpct"]
            hypo_ga = hypo_shots - hypo_sv # Or just use scenario['ga'] if we assume per-game

            # For simplicity, let's use the defined GA for the scenario per number of starts
            new_total_ga = current_ga + (scenario["ga"] * starts)
            new_total_sv = current_sv + hypo_sv
            new_total_shots = current_shots_against + hypo_shots

            # To calculate new GAA, we need total games played. Yahoo doesn't provide this.
            # We will simulate the SV% which is more reliable.
            new_svpct = new_total_sv / new_total_shots if new_total_shots > 0 else 0

            # We can't accurately calculate the new GAA without knowing the GP, so we'll pass a placeholder
            results.append({
                "name": f"{starts} {scenario['name']}(s)",
                "gaa": "N/A", # Placeholder
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
