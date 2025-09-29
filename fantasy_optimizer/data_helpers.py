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
from collections import defaultdict
import yahoo_fantasy_api as yfa
from thefuzz import process


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

def find_best_match(name, choices, score_cutoff=90):
    """
    Finds the best fuzzy match for a name from a dictionary of choices.

    Args:
        name (str): The name to match (e.g., from Yahoo).
        choices (dict): A dictionary mapping normalized_name -> original_name from the DB.
        score_cutoff (int): The minimum score (0-100) to consider a match.

    Returns:
        str: The best matching normalized_name, or None if no match meets the cutoff.
    """
    # extractOne returns a tuple of (best_match_original_name, score, best_match_normalized_key)
    # We provide the original names for matching but want the key back.
    best_match = process.extractOne(name, choices, score_cutoff=score_cutoff)

    if best_match:
        # The third element of the tuple is the key from the choices dict
        return best_match[2]
    return None

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

    # --- Pre-fetch all player names from DB for fuzzy matching ---
    cur.execute("SELECT player_name, normalized_name FROM projections")
    db_players = cur.fetchall()
    db_player_choices = {p['normalized_name']: p['player_name'] for p in db_players}


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

                # --- Fuzzy Match Fallback ---
                if not projection_row:
                    print(f"No exact match for '{player['name']}' ({normalized_player_name}). Trying fuzzy match...")
                    best_match_normalized = find_best_match(player['name'], db_player_choices)
                    if best_match_normalized:
                        print(f"Found fuzzy match: '{player['name']}' -> '{db_player_choices[best_match_normalized]}' ({best_match_normalized})")
                        cur.execute("SELECT * FROM projections WHERE normalized_name = ?", (best_match_normalized,))
                        projection_row = cur.fetchone()
                    else:
                        print(f"No suitable fuzzy match found for '{player['name']}'.")


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

    totals = defaultdict(float)
    daily_lineups = {}
    goalie_starts_details = []


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

        active_today = [p for p in simulated_roster if p.get('team') in schedules and date_str in schedules.get(p.get('team'), [])]


        optimal_roster_tuples = []
        if active_today:
            optimal_roster_tuples, _ = find_optimal_lineup(active_today)
            daily_lineups[date_str] = optimal_roster_tuples

            for player, pos_filled in optimal_roster_tuples:
                if 'G' in player.get('positions', ''):
                    goalie_starts_details.append({
                        'gaa': player['per_game_projections'].get('gaa', 0),
                        'ga': player['per_game_projections'].get('ga', 0),
                        'gs': player['per_game_projections'].get('gs', 1) # Assume 1 GS if not specified
                    })

                # FIX: Sum all per-game counting stats daily. Rate stats will be calculated once at the end.
                for stat, value in player['per_game_projections'].items():
                    # Skip non-stat fields and rate stats that need special calculation
                    if stat in ['player_name', 'team', 'positions', 'normalized_name', 'playerid', 'rank', 'age', 'svpct', 'gaa'] or value is None:
                        continue
                    try:
                        totals[stat] += float(value)
                    except (ValueError, TypeError):
                        continue
        current_date += timedelta(days=1)

    # Post-process goalie rate stats from the weekly totals
    if totals.get('sa', 0) > 0:
        totals['svpct'] = totals['sv'] / totals['sa']
    else:
        totals['svpct'] = 0

    total_ga_from_starts = sum(g['ga'] for g in goalie_starts_details)
    total_gs_from_starts = sum(g['gs'] for g in goalie_starts_details)
    if total_gs_from_starts > 0:
        totals['gaa'] = total_ga_from_starts / total_gs_from_starts
    else:
        totals['gaa'] = 0


    # Final rounding on all stats
    final_totals = {
        stat: round(value, 3 if stat in ['svpct', 'gaa'] else 2)
        for stat, value in totals.items()
    }
    # Pass back the raw totals for accurate live projection calculation
    final_totals['raw_ga'] = totals.get('ga', 0)
    final_totals['raw_gs'] = totals.get('gs', 0)
    final_totals['raw_sv'] = totals.get('sv', 0)
    final_totals['raw_sa'] = totals.get('sa', 0)

    return final_totals, daily_lineups, simulated_roster


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

def get_healthy_free_agents(lg):
    """
    Fetches all free agents AND players on waivers from Yahoo for a given league
    and filters out players with an injury status that makes them eligible for an IR slot.
    It also adds an 'availability' status ('FA' or 'W') to each player.
    """
    print("Fetching available players (Free Agents & Waivers) from Yahoo API...")
    available_players = []

    # 1. Fetch Free Agents by position
    for pos in ['C', 'LW', 'RW', 'D', 'G']:
        try:
            print(f"Fetching free agents for position: {pos}")
            fas = lg.free_agents(pos)
            for p in fas:
                p['availability'] = 'FA'
            available_players.extend(fas)
        except Exception as e:
            print(f"Could not fetch FAs for position {pos}: {e}")

    # 2. Fetch Players on Waivers
    try:
        print("Fetching players on waivers...")
        waiver_players = lg.waivers()
        for p in waiver_players:
            p['availability'] = 'W'
        available_players.extend(waiver_players)
        print(f"Found {len(waiver_players)} players on waivers.")
    except Exception as e:
        print(f"Could not fetch players on waivers: {e}")

    # Remove duplicates that might appear in both lists
    unique_players = list({p['player_id']: p for p in available_players}.values())
    print(f"Found {len(unique_players)} total unique available players.")

    # 3. Filter out injured players
    INJURY_STATUSES_TO_EXCLUDE = ['O', 'DTD', 'IR', 'IR-LT', 'NA', 'IL']
    healthy_available_players = [p for p in unique_players if p.get('status', '') not in INJURY_STATUSES_TO_EXCLUDE]

    print(f"Found {len(healthy_available_players)} healthy available players.")
    return healthy_available_players
