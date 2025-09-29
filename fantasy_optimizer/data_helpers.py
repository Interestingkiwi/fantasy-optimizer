"""
This module contains helper functions for fetching and processing data
from the database and the Yahoo Fantasy API. It keeps the route handlers
in routes.py cleaner and focused on request/response logic.
"""
import sqlite3
import json
import re
import unicodedata
from datetime import datetime, timedelta
import yahoo_fantasy_api as yfa

from . import config

def normalize_name(name):
    """
    Normalizes a player name by converting to lowercase, removing diacritics,
    and removing all non-alphanumeric characters.
    """
    if not name:
        return ""
    # NFD form separates combined characters into base characters and diacritics
    nfkd_form = unicodedata.normalize('NFKD', name.lower())
    # Keep only ASCII characters
    ascii_name = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    # Remove all non-alphanumeric characters (keeps letters and numbers)
    return re.sub(r'[^a-z0-9]', '', ascii_name)

def get_user_leagues(gm):
    """Fetches all hockey leagues for the authenticated user."""
    # FIX: Updated the year from 2024 to 2025 to fetch leagues for the current 2025-26 season.
    leagues_data = gm.league_ids(year=2025)
    leagues = []
    for league_id in leagues_data:
        try:
            lg = gm.to_league(league_id)
            leagues.append({
                'league_id': league_id,
                'name': lg.settings().get('name')
            })
        except Exception as e:
            print(f"Could not fetch info for league {league_id}: {e}")
            continue
    return leagues

def get_weekly_roster_data(gm, league_id, week_num):
    """
    Fetches and combines roster, projection, and schedule data for a given league and week.
    """
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
        game_count = sum(1 for d_str in schedule_dates if week_start_date <= datetime.fromisoformat(d_str).date() <= week_end_date)
        games_this_week[team_tricode] = game_count

    # --- 3. Fetch Yahoo Fantasy Rosters ---
    try:
        lg = gm.to_league(league_id)
        all_rosters = {}
        all_teams_data = lg.teams()

        # --- 4. Combine all data for each player ---
        for team_key, team_info in all_teams_data.items():
            team_name = team_info['name']
            team = lg.to_team(team_key)
            # FIX: Pass the datetime.date object directly to the roster method.
            # The yahoo_fantasy_api library expects a date object, and passing an isoformat string
            # was causing an AttributeError ('str' object has no attribute 'strftime') internally.
            roster = team.roster(day=week_end_date) # Roster for the end of the week
            roster_data = []

            for player in roster:
                # Normalize the player name from Yahoo for a robust DB lookup.
                normalized_player_name = normalize_name(player['name'])

                # FIX: Handle players with the same name (e.g., Sebastian Aho, Elias Pettersson)
                # Projections may distinguish them by appending (F) or (D), which our normalize_name function includes.
                # We need to construct the same normalized name from Yahoo data.
                if normalized_player_name in ['sebastianaho', 'eliaspettersson']:
                    is_forward = any(pos in ['C', 'LW', 'RW', 'F'] for pos in player['eligible_positions'])
                    is_defense = 'D' in player['eligible_positions']

                    if is_forward and not is_defense:
                        normalized_player_name = f"{normalized_player_name}f"
                    elif is_defense and not is_forward:
                        normalized_player_name = f"{normalized_player_name}d"

                cur.execute("SELECT * FROM projections WHERE normalized_name = ?", (normalized_player_name,))
                projection_row = cur.fetchone()

                player_projections = dict(projection_row) if projection_row else {}
                player_team_tricode = player_projections.get('team', 'N/A').upper() if player_projections else 'N/A'

                weekly_projections = {}
                num_games = games_this_week.get(player_team_tricode, 0)
                # FIX: Ensure all numeric stats are processed, not just a subset.
                for stat, value in player_projections.items():
                    if stat not in ['player_name', 'team', 'positions', 'normalized_name', 'playerid', 'rank', 'age'] and value is not None:
                        try:
                            # Note: The database should already contain per-game stats.
                            weekly_projections[stat] = round(float(value) * num_games, 2)
                        except (ValueError, TypeError):
                            weekly_projections[stat] = 0
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
        # Return a more specific error if the league ID is invalid
        if "invalid" in str(e).lower() and "league" in str(e).lower():
             return {"error": f"Invalid League ID: {league_id}. Please check the ID and try again."}
        return {"error": f"An error occurred fetching Yahoo data: {e}"}

def calculate_optimized_totals(roster, week_num, schedules, week_dates, transactions=[]):
    from .optimization_logic import find_optimal_lineup

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
            normalized_add_name = normalize_name(move['add'])
            cur.execute("SELECT * FROM projections WHERE normalized_name = ?", (normalized_add_name,))
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


def get_live_stats_for_team(lg, team_name, week_num):
    """
    Fetches live stats for a specific team for a given fantasy week.
    """
    try:
        all_teams = lg.teams()
        team_key = next((tk for tk, t_data in all_teams.items() if t_data['name'] == team_name), None)

        if not team_key:
            print(f"Warning: Team key not found for team name '{team_name}'")
            return {}

        matchup_data = lg.matchup(team_key, week=week_num)

        # The matchup data is directly the stats for that team in that week
        if matchup_data:
             return {stat: val for stat, val in matchup_data.items() if isinstance(val, (int, float, str))}

        print(f"No live matchup data found for {team_name} in week {week_num}.")
        return {}

    except Exception as e:
        print(f"Could not fetch live matchup data for {team_name} (week {week_num}): {e}")
        return {}
