# setup_database.py
import sqlite3
import csv
import re
import requests
import json
import time
import unicodedata
from datetime import date, timedelta
from collections import Counter, defaultdict

# --- Configuration ---
DB_FILE = "projections.db"
SKATER_CSV_FILE = "projections.csv"
GOALIE_CSV_FILE = "gprojections.csv"
START_DATE = date(2025, 10, 7)
END_DATE = date(2026, 4, 17)
NHL_TEAM_COUNT = 32

TEAM_TRICODES = [
    "ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL",
    "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NSH", "NJD", "NYI",
    "NYR", "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR",
    "UTA", "VAN", "VGK", "WSH", "WPG"
]

TEAM_TRICODE_MAP = {
    "TB": "TBL",
    "NJ": "NJD",
    "SJ": "SJS",
    "LA": "LAK",
    "MON": "MTL",
    "WAS": "WSH"
}


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

def sanitize_header(header_list):
    """Sanitizes a list of header strings for SQL compatibility."""
    sanitized = []

    # Mapping from CSV header names to the abbreviations used in the app
    stat_mapping = {
        'goals': 'g',
        'assists': 'a',
        'points': 'pts',
        'pp_points': 'ppp',
        'hits': 'hit',
        'sog': 'sog',
        'blk': 'blk',
        'w': 'w',
        'so': 'so',
        'sv%': 'svpct',
        'ga': 'ga',
        'plus_minus': 'plus_minus',
        'shg': 'shg',
        'sha': 'sha',
        'shp': 'shp',
        'pim': 'pim',
        'fow': 'fow',
        'fol': 'fol',
        'ppg': 'ppg',
        'ppa': 'ppa',
        'gaa': 'gaa',
        'gs': 'gs',
        'sv': 'sv',
        'sa': 'sa',
        'qs': 'qs'
    }

    for h in header_list:
        clean_h = h.strip().lower()
        if clean_h == '"+/-"':
            clean_h = 'plus_minus'
        else:
            clean_h = re.sub(r'[^a-z0-9_%]', '', clean_h.replace(' ', '_'))

        sanitized.append(stat_mapping.get(clean_h, clean_h))

    return sanitized

def calculate_per_game_stats(row, gp_index, stat_indices):
    """
    Takes a players total projected stat for a column, and converts it to a
    per game figure by dividing it by expected games played.
    """
    try:
        # Get the number of games played, default to 0 if it's not a valid number
        games_played = float(row[gp_index])
    except (ValueError, IndexError):
        games_played = 0.0

    # If games played is 0, we can't divide. All per-game stats will be 0.
    if games_played == 0:
        for i in stat_indices:
            if i < len(row):
                row[i] = 0.0
        return row

    # Loop through the stat columns and calculate the per-game average
    for i in stat_indices:
        if i < len(row):
            try:
                stat_value = float(row[i])
                row[i] = round(stat_value / games_played, 4) # Calculate and round to 4 decimal places
            except (ValueError, IndexError, TypeError):
                # If the stat itself isn't a valid number, just set it to 0
                row[i] = 0.0
    return row

def setup_projections_table(cursor):
    """Creates and populates the 'projections' table from both skater and goalie CSV files."""
    print("--- Setting up Projections Table ---")
    try:
        # Part 1: Define schema from both files and create table
        def get_header_from_file(file_path):
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                return next(csv.reader(f))

        skater_header_raw = get_header_from_file(SKATER_CSV_FILE)
        goalie_header_raw = get_header_from_file(GOALIE_CSV_FILE)

        sanitized_skater_headers = sanitize_header(skater_header_raw)
        sanitized_goalie_headers = sanitize_header(goalie_header_raw)

        all_headers = list(dict.fromkeys(sanitized_skater_headers + sanitized_goalie_headers))
        final_headers = [h for h in all_headers if h]

        if 'player_name' not in final_headers: raise ValueError("'player_name' column not found.")

        columns_def_parts = [f'"{c}" REAL' for c in final_headers if c not in ['player_name', 'positions']]
        columns_def_parts.insert(0, 'player_name TEXT PRIMARY KEY')
        columns_def_parts.insert(1, 'positions TEXT')
        columns_def_parts.append('normalized_name TEXT')

        create_table_sql = f'CREATE TABLE projections ({", ".join(columns_def_parts)})'
        create_index_sql = 'CREATE INDEX idx_normalized_name ON projections(normalized_name)'
        cursor.execute("DROP TABLE IF EXISTS projections")
        cursor.execute(create_table_sql)
        cursor.execute(create_index_sql)
        print("Table 'projections' and index created with a unified schema.")

        # Part 2: Process data in memory from both files
        player_data = {}

        # Process Skaters from projections.csv
        with open(SKATER_CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header_raw = next(reader)
            header_lower = [h.strip().lower() for h in header_raw]
            sanitized_headers = sanitize_header(header_raw)

            try:
                p_name_idx = header_lower.index('player name')
                gp_idx = header_lower.index('gp')
                pos_idx = header_lower.index('positions')
            except ValueError as e:
                raise ValueError(f"Missing column in {SKATER_CSV_FILE}: {e}")

            skater_stats_to_exclude = [
                'player name', 'age', 'positions', 'team', 'salary', 'gp org', 'gp',
                'toi org es', 'toi org pp', 'toi org pk', 'toi es', 'toi pp', 'toi pk', 'total toi',
                'rank', 'playerid', 'fantasy team'
            ]
            skater_stat_indices = [
                i for i, h in enumerate(header_lower)
                if h not in skater_stats_to_exclude and h.strip() != ''
            ]


            for row in reader:
                if not row or (pos_idx < len(row) and 'G' in row[pos_idx]): continue
                calculate_per_game_stats(row, gp_idx, skater_stat_indices)
                player_name = row[p_name_idx]
                if not player_name: continue
                normalized = normalize_name(player_name)

                data_dict = {sanitized_headers[i]: val for i, val in enumerate(row)}
                team_abbr = data_dict.get('team', '').upper()
                if team_abbr in TEAM_TRICODE_MAP:
                    data_dict['team'] = TEAM_TRICODE_MAP[team_abbr]
                player_data[normalized] = data_dict

                player_data[normalized]['normalized_name'] = normalized

        # Process Goalies from gprojections.csv, updating or adding to the player_data dict
        with open(GOALIE_CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header_raw = next(reader)
            header_lower = [h.strip().lower() for h in header_raw]
            sanitized_headers = sanitize_header(header_raw)

            try:
                p_name_idx = header_lower.index('player name')
                gp_goalie_idx = header_lower.index('gs')  # Assuming 'GS' for games started
            except ValueError as e:
                raise ValueError(f"Missing column in {GOALIE_CSV_FILE}: {e}")

            goalie_stats_to_exclude = [
                'player name', 'team', 'age', 'position', 'salary', 'gs', 'sv%', 'gaa',
                'rank', 'playerid', 'fantasy team'
            ]
            goalie_stat_indices = [
                i for i, h in enumerate(header_lower)
                if h not in goalie_stats_to_exclude and h.strip() != ''
            ]

            for row in reader:
                if not row: continue
                calculate_per_game_stats(row, gp_goalie_idx, goalie_stat_indices)
                player_name = row[p_name_idx]
                if not player_name: continue
                normalized = normalize_name(player_name)

                goalie_row_data = {sanitized_headers[i]: val for i, val in enumerate(row)}
                team_abbr = goalie_row_data.get('team', '').upper()
                if team_abbr in TEAM_TRICODE_MAP:
                    goalie_row_data['team'] = TEAM_TRICODE_MAP[team_abbr]

                if 'positions' not in goalie_row_data or not goalie_row_data['positions']:
                    goalie_row_data['positions'] = 'G'

                if normalized in player_data:
                    player_data[normalized].update(goalie_row_data)
                else:
                    goalie_row_data['normalized_name'] = normalized
                    player_data[normalized] = goalie_row_data

        print(f"Processed data for {len(player_data)} unique players from both files.")

        # Part 3: Insert combined data into the database
        insert_headers = final_headers + ['normalized_name']
        placeholders = ", ".join(['?'] * len(insert_headers))
        insert_sql = f'INSERT OR REPLACE INTO projections ({", ".join(f"`{h}`" for h in insert_headers)}) VALUES ({placeholders})'

        rows_to_insert = []
        for normalized_name, data_dict in player_data.items():
            ordered_row = tuple(data_dict.get(h, None) for h in insert_headers)
            rows_to_insert.append(ordered_row)

        cursor.executemany(insert_sql, rows_to_insert)
        print(f"Populated 'projections' table with {len(rows_to_insert)} rows.")

    except FileNotFoundError as e:
        print(f"ERROR: A required CSV file was not found: {e.filename}")
        raise
    except ValueError as e:
        print(f"ERROR: {e}")
        raise

def get_full_nhl_schedule(start_date, end_date):
    """Fetches the entire season's NHL game schedule."""
    all_games = {}
    current_date = start_date
    print("\n--- Fetching Full NHL Schedule ---")
    while current_date <= end_date:
        url = f"https://api-web.nhle.com/v1/schedule/{current_date.strftime('%Y-%m-%d')}"
        print(f"Fetching schedule for week of {current_date.strftime('%Y-%m-%d')}...")
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            for week_data in data.get('gameWeek', []):
                for game in week_data.get('games', []):
                    game_key = f"{week_data.get('date')}-{game.get('homeTeam', {}).get('abbrev')}-{game.get('awayTeam', {}).get('abbrev')}"
                    if game_key not in all_games:
                        all_games[game_key] = {'date': week_data.get('date'), 'home_team': game.get('homeTeam', {}).get('abbrev'), 'away_team': game.get('awayTeam', {}).get('abbrev')}
        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not fetch schedule for week {current_date.strftime('%Y-%m-%d')}: {e}")
        current_date += timedelta(days=7)
        time.sleep(0.1)
    game_list = list(all_games.values())
    print(f"Successfully fetched {len(game_list)} unique games.")
    return game_list

def setup_schedule_tables(cursor, games):
    """Creates and populates all schedule-related tables."""
    print("\n--- Setting up Schedule Tables ---")
    if not games:
        print("No game data to process for schedule tables.")
        return

    # 1. Schedule Table
    cursor.execute("DROP TABLE IF EXISTS schedule")
    cursor.execute("CREATE TABLE schedule (game_id INTEGER PRIMARY KEY, game_date TEXT, home_team TEXT, away_team TEXT)")
    cursor.executemany("INSERT INTO schedule (game_date, home_team, away_team) VALUES (?, ?, ?)", [(g['date'], g['home_team'], g['away_team']) for g in games])
    print("Table 'schedule' created and populated.")

    # 2. Fantasy Weeks Table (with special logic for Week 18)
    cursor.execute("DROP TABLE IF EXISTS fantasy_weeks")
    cursor.execute("CREATE TABLE fantasy_weeks (week_number INTEGER PRIMARY KEY, start_date TEXT, end_date TEXT)")

    first_monday = START_DATE - timedelta(days=START_DATE.weekday())
    week_number = 1
    current_date = first_monday

    while current_date <= END_DATE:
        if week_number == 18:
            # Special handling for the long Week 18 (Olympic Break)
            week_start = date(2026, 2, 2)
            week_end = date(2026, 3, 1)
            print(f"Applying special dates for Week 18: {week_start} to {week_end}")
        else:
            # Standard 7-day week
            week_start = current_date
            week_end = current_date + timedelta(days=6)

        cursor.execute("INSERT INTO fantasy_weeks VALUES (?, ?, ?)", (week_number, week_start.isoformat(), week_end.isoformat()))

        # Prepare for the next iteration
        if week_number == 18:
            # After the special week 18, week 19 starts on the next day (Monday)
            current_date = week_end + timedelta(days=1)
        else:
            # Normal weekly increment
            current_date += timedelta(days=7)

        week_number += 1

    print("Table 'fantasy_weeks' created and populated.")

    # 3. Team Schedules Table
    cursor.execute("DROP TABLE IF EXISTS team_schedules")
    cursor.execute("CREATE TABLE team_schedules (team_tricode TEXT PRIMARY KEY, schedule_json TEXT)")
    schedules_by_team = defaultdict(list)
    for game in games:
        schedules_by_team[game['home_team']].append(game['date'])
        schedules_by_team[game['away_team']].append(game['date'])
    team_schedule_data = [(team, json.dumps(sorted(dates))) for team, dates in schedules_by_team.items()]
    cursor.executemany("INSERT INTO team_schedules VALUES (?, ?)", team_schedule_data)
    print("Table 'team_schedules' created and populated.")

    # 4. Off Days Table
    cursor.execute("DROP TABLE IF EXISTS off_days")
    cursor.execute("CREATE TABLE off_days (off_day_date TEXT PRIMARY KEY)")
    games_per_day = Counter(g['date'] for g in games)
    off_days = [(day,) for day, count in games_per_day.items() if count * 2 < NHL_TEAM_COUNT]
    cursor.executemany("INSERT INTO off_days VALUES (?)", sorted(off_days))
    print(f"Table 'off_days' created and populated with {len(off_days)} dates.")

def main():
    """Main function to initialize the entire database."""
    print(f"Connecting to database file: {DB_FILE}")
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    try:
        # Step 1: Set up the projections table from local CSV
        setup_projections_table(cur)

        # Step 2: Fetch schedule data from the NHL API
        schedule_data = get_full_nhl_schedule(START_DATE, END_DATE)

        # Step 3: Set up all schedule-related tables
        setup_schedule_tables(cur, schedule_data)

        con.commit()
        print(f"\n✅✅✅ Database setup complete! {DB_FILE} is ready. ✅✅✅")
    except Exception as e:
        print(f"\n❌ An error occurred during database setup: {e}")
        con.rollback()
    finally:
        con.close()
        print("Database connection closed.")

if __name__ == '__main__':
    main()
