"""
This module contains helper functions for fetching and processing data
from the database and the Yahoo Fantasy API. It keeps the route handlers
in routes.py cleaner and focused on request/response logic.
"""
import os
import sqlite3
import json
from datetime import datetime, timedelta
import yahoo_fantasy_api as yfa
from yahoo_oauth import OAuth2

from . import config

def get_weekly_roster_data(week_num):
    # This function is unchanged from the original app.py
    # ... (code for get_weekly_roster_data remains here) ...
    # --- 1. Connect to DB and get week start/end dates ---
    con = sqlite3.connect(config.DB_FILE)
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
    if not os.path.exists(config.YAHOO_CREDENTIALS_FILE) and not os.environ.get('YAHOO_PRIVATE_JSON'):
         return {"error": "Yahoo credentials not found"}

    try:
        oauth = OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE)
        if not oauth.token_is_valid(): oauth.refresh_access_token()

        game = yfa.Game(oauth, 'nhl')
        lg = game.to_league(config.YAHOO_LEAGUE_KEY)
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

def calculate_optimized_totals(roster, week_num, schedules, week_dates, transactions=[]):
    # This function is unchanged from the original app.py
    # ... (code for calculate_optimized_totals remains here) ...
    from .optimization_logic import find_optimal_lineup # Local import to avoid circular dependency

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
            con = sqlite3.connect(config.DB_FILE)
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


def get_live_stats_for_team(team_name, week_num):
    """
    Fetches live stats for a specific team for a given fantasy week.
    This helps reuse the API call logic.
    """
    try:
        oauth = OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE)
        if not oauth.token_is_valid():
            oauth.refresh_access_token()

        game = yfa.Game(oauth, 'nhl')
        lg = game.to_league(config.YAHOO_LEAGUE_KEY)

        # Get the team key for the given team name
        all_teams = lg.teams()
        team_key = None
        for tk, t_data in all_teams.items():
            if t_data['name'] == team_name:
                team_key = tk
                break

        if not team_key:
            print(f"Warning: Team key not found for team name '{team_name}'")
            return {}

        # CORRECTED: Use lg.matchups() and find the specific matchup
        matchups_data = lg.matchups(week=week_num)

        for matchup in matchups_data.get('matchups', []):
            teams = matchup.get('teams', [])
            for team in teams:
                if team['team_key'] == team_key:
                    # Found the right team, return its stats
                    return team.get('stats', {})

        # If no matchup was found for the team this week (e.g., future week)
        print(f"No live matchup data found for {team_name} in week {week_num}.")
        return {}

    except Exception as e:
        # Handle cases where matchups might not be available (e.g., API errors, off-season)
        print(f"Could not fetch live matchup data for {team_name} (week {week_num}): {e}")
        return {} # Return empty dictionary on failure
