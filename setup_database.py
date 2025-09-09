# setup_database.py
import sqlite3
import csv
import re
import requests
import json
import time
from datetime import date, timedelta
from collections import Counter, defaultdict

# --- Configuration ---
DB_FILE = "projections.db"
CSV_FILE = "projections.csv"
START_DATE = date(2025, 10, 7)
END_DATE = date(2026, 4, 17)
NHL_TEAM_COUNT = 32

TEAM_TRICODES = [
    "ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL",
    "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NSH", "NJD", "NYI",
    "NYR", "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR",
    "UTA", "VAN", "VGK", "WSH", "WPG"
]

def setup_projections_table(cursor):
    """Creates and populates the 'projections' table from the CSV file."""
    print("--- Setting up Projections Table ---")
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header_raw = next(reader)

            def sanitize_header(header):
                return [re.sub(r'[^a-zA-Z0-9_]', '', h.strip().replace(' ', '_').lower()) for h in header]

            sql_headers_raw = sanitize_header(header_raw)
            final_headers, indices_to_keep = [], []
            for i, sql_h in enumerate(sql_headers_raw):
                if sql_h:
                    final_headers.append(sql_h)
                    indices_to_keep.append(i)

            if 'player_name' not in final_headers: raise ValueError("'Player Name' column not found.")
            if 'positions' not in final_headers: raise ValueError("'Positions' column not found.")

            columns_def_parts = [
                'player_name TEXT PRIMARY KEY' if c == 'player_name' else
                'positions TEXT' if c == 'positions' else
                f'"{c}" REAL' for c in final_headers
            ]

            create_table_sql = f'CREATE TABLE projections ({", ".join(columns_def_parts)})'
            cursor.execute("DROP TABLE IF EXISTS projections")
            cursor.execute(create_table_sql)
            print("Table 'projections' created.")

        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader) # Skip header

            placeholders = ", ".join(['?'] * len(final_headers))
            insert_sql = f'INSERT OR REPLACE INTO projections ({", ".join(f"`{h}`" for h in final_headers)}) VALUES ({placeholders})'

            rows_to_insert = [[row[i] for i in indices_to_keep] for row in reader if len(row) >= len(header_raw)]
            cursor.executemany(insert_sql, rows_to_insert)
            print(f"Populated 'projections' table with {len(rows_to_insert)} rows.")

    except FileNotFoundError:
        print(f"ERROR: {CSV_FILE} not found. Cannot set up projections table.")
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
