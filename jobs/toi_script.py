import requests
import pandas as pd
from datetime import date, timedelta
import time
import sqlite3
import os
import numpy as np
import sys


MOUNT_PATH = "/var/data/dbs"

DB_FILE = os.path.join(MOUNT_PATH, "special_teams.db")
PROJECTIONS_DB_FILE = os.path.join(MOUNT_PATH, "projections.db")


FRANCHISE_TO_TRICODE_MAP = {
    "Anaheim Ducks": "ANA",
    "Boston Bruins": "BOS",
    "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY",
    "Carolina Hurricanes": "CAR",
    "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL",
    "Columbus Blue Jackets": "CBJ",
    "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET",
    "Edmonton Oilers": "EDM",
    "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK",
    "Minnesota Wild": "MIN",
    "Montréal Canadiens": "MTL",
    "Nashville Predators": "NSH",
    "New Jersey Devils": "NJD",
    "New York Islanders": "NYI",
    "New York Rangers": "NYR",
    "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA",
    "St. Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL",
    "Toronto Maple Leafs": "TOR",
    "Utah Mammoth": "UTA",
    "Vancouver Canucks": "VAN",
    "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH",
    "Winnipeg Jets": "WPG"
}

def setup_database():
    """Creates the powerplay_stats table in the SQLite database if it doesn't exist."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Use PRIMARY KEY on (date_, nhlplayerid) to prevent exact duplicates
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS powerplay_stats (
            date_ TEXT,
            nhlplayerid INTEGER,
            skaterFullName TEXT,
            teamAbbrevs TEXT,
            ppTimeOnIce INTEGER,
            ppTimeOnIcePctPerGame REAL,
            ppAssists INTEGER,
            ppGoals INTEGER,
            PRIMARY KEY (date_, nhlplayerid)
        )
        ''')
        # Add metadata table creation
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS table_metadata (
            id INTEGER PRIMARY KEY DEFAULT 1,
            start_date TEXT,
            end_date TEXT
        )
        ''')
        #Add Team Data Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_standings (
            team_tricode TEXT PRIMARY KEY,
            point_pct TEXT,
            goals_against_per_game REAL,
            games_played INTEGER
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_stats_summary (
            team_tricode TEXT PRIMARY KEY,
            pp_pct REAL,
            pk_pct REAL,
            gf_gm REAL,
            ga_gm REAL,
            sogf_gm REAL,
            soga_gm REAL
        )
        ''')
        # --- NEW TABLE FOR WEEKLY PP% / PK% ---
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_stats_weekly (
            team_tricode TEXT PRIMARY KEY,
            pp_pct_weekly REAL,
            pk_pct_weekly REAL,
            gf_gm_weekly REAL,
            ga_gm_weekly REAL,
            sogf_gm_weekly REAL,
            soga_gm_weekly REAL
        )
        ''')
        # Add scoring_to_date table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scoring_to_date (
            nhlplayerid INTEGER PRIMARY KEY,
            skaterFullName TEXT,
            teamAbbrevs TEXT,
            gamesPlayed INTEGER,
            goals INTEGER,
            assists INTEGER,
            points INTEGER,
            plusMinus TEXT,
            penaltyMinutes INTEGER,
            ppGoals INTEGER,
            ppAssists INTEGER,
            ppPoints INTEGER,
            shootingPct REAL,
            timeonIcePerGame REAL,
            shots INTEGER
        )
        ''')
        # Add bangers_to_date table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bangers_to_date (
            nhlplayerid INTEGER PRIMARY KEY,
            skaterFullName TEXT,
            teamAbbrevs TEXT,
            blocksPerGame INTEGER,
            hitsPerGame INTEGER
        )
        ''')
        # Add all_goalie_data table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS goalie_to_date (
            nhlplayerid INTEGER PRIMARY KEY,
            goalieFullName TEXT,
            teamAbbrevs TEXT,
            gamnesStarted INTEGER,
            gamesPlayed INTEGER,
            goalsAgainstAverage REAL,
            losses INTEGER,
            savePct REAL,
            saves INTEGER,
            shotsAgainst INTEGER,
            shutouts INTEGER,
            wins INTEGER,
            goalsAgainst INTEGER,
            startpct INTEGER
        )
        ''')
        conn.commit()
        print(f"Database '{DB_FILE}' and table 'powerplay_stats' are set up.")
    except sqlite3.Error as e:
        print(f"An error occurred with the database setup: {e}")
    finally:
        if conn:
            conn.close()

def get_last_run_end_date():
    """Fetches the last successfully recorded end_date from metadata."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Check if table exists first, to prevent error on first-ever run
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='table_metadata'")
        if cursor.fetchone() is None:
            return None

        cursor.execute("SELECT end_date FROM table_metadata WHERE id = 1")
        result = cursor.fetchone()
        if result and result[0]:
            return date.fromisoformat(result[0])
    except sqlite3.Error as e:
        print(f"Error reading metadata, will fetch full 7-day range. Error: {e}")
    finally:
        if conn:
            conn.close()
    return None

def run_database_cleanup(target_start_date):
    """Deletes records from powerplay_stats older than the target start date."""
    conn = None
    target_start_str = target_start_date.strftime("%Y-%m-%d")
    print(f"\nDeleting old records from database (before {target_start_str})...")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM powerplay_stats WHERE date_ < ?", (target_start_str,))
        conn.commit()
        print(f"Deleted {cursor.rowcount} old records.")
    except sqlite3.Error as e:
        print(f"An error occurred during database cleanup: {e}")
    finally:
        if conn:
            conn.close()

def update_metadata(start_date, end_date):
    """Updates the metadata table with the new start and end dates of the data window."""
    conn = None
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    print(f"Updating metadata: start_date={start_str}, end_date={end_str}")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Use UPSERT logic (INSERT ON CONFLICT)
        cursor.execute('''
        INSERT INTO table_metadata (id, start_date, end_date)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            start_date = excluded.start_date,
            end_date = excluded.end_date
        ''', (start_str, end_str))
        conn.commit()
        print("Metadata updated successfully.")
    except sqlite3.Error as e:
        print(f"An error occurred while updating metadata: {e}")
    finally:
        if conn:
            conn.close()

def create_last_game_pp_table(db_file):
    """
    Creates/replaces the 'last_game_pp' table with all player rows from
    the most recent game for each team.
    """
    print("\n--- Creating/Updating 'last_game_pp' Table (Team-Based) ---")
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # Drop the table if it already exists to ensure a fresh build
        cursor.execute("DROP TABLE IF EXISTS last_game_pp")

        # 1. Find the max date for each team
        # 2. Join that result back to the main table
        # 3. Create the new table from all matching rows
        query = """
        CREATE TABLE last_game_pp AS
        SELECT
            t1.*
        FROM
            powerplay_stats t1
        INNER JOIN (
            SELECT
                teamAbbrevs,
                MAX(date_) as max_date
            FROM
                powerplay_stats
            GROUP BY
                teamAbbrevs
        ) t2 ON t1.teamAbbrevs = t2.teamAbbrevs AND t1.date_ = t2.max_date;
        """

        cursor.execute(query)
        conn.commit()

        # Log how many records were created
        cursor.execute("SELECT COUNT(*) FROM last_game_pp")
        count = cursor.fetchone()[0]
        print(f"Successfully created 'last_game_pp' table with {count} total player entries (from teams' last games).")

    except sqlite3.Error as e:
        print(f"An error occurred while creating 'last_game_pp' table: {e}")
    finally:
        if conn:
            conn.close()

def create_last_week_pp_table(db_file):
    """
    Creates/replaces the 'last_week_pp' table with aggregated 7-day stats
    for each player, using team total games as the divisor for averages.
    """
    print("\n--- Creating/Updating 'last_week_pp' Table (Aggregated) ---")
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # Drop the table if it already exists
        cursor.execute("DROP TABLE IF EXISTS last_week_pp")

        # This query does all the work:
        # 1. 'team_game_counts' CTE: Counts distinct games for each team in the (7-day) table.
        # 2. 'player_sums' CTE: SUMs all stats for each player (grouped by player AND team).
        # 3. Final SELECT: Joins the two CTEs and performs the custom division.
        query = """
        CREATE TABLE last_week_pp AS

        -- Step 1: Count distinct games played by each team in the last 7 days
        WITH team_game_counts AS (
            SELECT
                teamAbbrevs,
                COUNT(DISTINCT date_) as team_games_played
            FROM
                powerplay_stats
            GROUP BY
                teamAbbrevs
        ),

        -- Step 2: Sum all stats for each player (per team, in case of trades)
        player_sums AS (
            SELECT
                nhlplayerid,
                teamAbbrevs,
                MAX(skaterFullName) as skaterFullName,
                SUM(ppTimeOnIce) as total_ppTimeOnIce,
                SUM(ppTimeOnIcePctPerGame) as total_ppTimeOnIcePctPerGame,
                SUM(ppAssists) as total_ppAssists,
                SUM(ppGoals) as total_ppGoals,
                COUNT(date_) as player_games_played
            FROM
                powerplay_stats
            GROUP BY
                nhlplayerid, teamAbbrevs
        )

        -- Step 3: Join them and perform the custom average calculation
        SELECT
            ps.nhlplayerid,
            ps.skaterFullName,
            ps.teamAbbrevs,

            -- Custom Average: Total Stat / Team Games Played
            -- We CAST to REAL to ensure floating point division (e.g., 5 / 3.0 = 1.66)
            CAST(ps.total_ppTimeOnIce AS REAL) / tgc.team_games_played AS avg_ppTimeOnIce,
            CAST(ps.total_ppTimeOnIcePctPerGame AS REAL) / tgc.team_games_played AS avg_ppTimeOnIcePctPerGame,

            -- Simple Sums
            ps.total_ppAssists,
            ps.total_ppGoals,

            -- Context Columns
            ps.player_games_played,
            tgc.team_games_played
        FROM
            player_sums ps
        JOIN
            team_game_counts tgc ON ps.teamAbbrevs = tgc.teamAbbrevs;
        """

        cursor.execute(query)
        conn.commit()

        # Log how many records were created
        cursor.execute("SELECT COUNT(*) FROM last_week_pp")
        count = cursor.fetchone()[0]
        print(f"Successfully created 'last_week_pp' table with {count} aggregated player entries.")

    except sqlite3.Error as e:
        print(f"An error occurred while creating 'last_week_pp' table: {e}")
    finally:
        if conn:
            conn.close()

def fetch_daily_pp_stats():
    """
    Fetches NHL powerplay stats for the previous 7 days, not including today.
    It queries the API day-by-day to get per-game stats and handles pagination.
    """

    # --- 1. Define Fields and Data Structures ---

    # These are the fields we want to pull from the API response
    FIELDS_TO_EXTRACT = [
        "playerId",
        "skaterFullName",
        "teamAbbrevs",
        "ppTimeOnIce",
        "ppTimeOnIcePctPerGame",
        "ppAssists",
        "ppGoals"
    ]

    # This maps the API field name to the final column name you requested
    COLUMN_REMAP = {
        "playerId": "nhlplayerid"
    }

    # This list will hold all the dictionaries of player data
    all_player_data = []

    # --- 2. Calculate Date Range ---

    today = date.today()
    target_end_date = today - timedelta(days=1)   # Yesterday
    target_start_date = today - timedelta(days=7) # 7 days ago

    last_run_end_date = get_last_run_end_date()

    if last_run_end_date:
        # Start querying from the day *after* the last run
        query_start_date = last_run_end_date + timedelta(days=1)
        # But if there's a large gap, don't query data older than the target 7-day window
        if query_start_date < target_start_date:
            query_start_date = target_start_date
        print(f"Last run found. Data is current up to {last_run_end_date}.")
    else:
        # No metadata found, fetch the full 7-day window
        print("No metadata found. Fetching full 7-day window.")
        query_start_date = target_start_date

    query_end_date = target_end_date

    # Run database cleanup *before* fetching, based on the target window
    run_database_cleanup(target_start_date)

    # Check if we are already up to date
    if query_start_date > query_end_date:
        print(f"Data is already up to date (as of {last_run_end_date}). No new data to fetch.")
        # We still update metadata to reflect the new cleanup (start_date)
        if last_run_end_date: # Only update if last_run_end_date is not None
            update_metadata(target_start_date, last_run_end_date)
        return False # Return False to indicate no new data was fetched

    print(f"Target data window: {target_start_date} to {target_end_date}")
    print(f"Fetching new data for: {query_start_date} to {query_end_date}")

    # Create a list of all date strings we need to query
    dates_to_query = []
    current_date = query_start_date
    while current_date <= query_end_date:
        dates_to_query.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)

    # --- 3. Loop Through Each Day and Fetch Data ---

    BASE_URL = "https://api.nhle.com/stats/rest/en/skater/powerplay"

    for query_date in dates_to_query:
        print(f"\n--- Querying for date: {query_date} ---")

        start_index = 0
        limit = 100

        # This inner loop handles pagination for a single day
        while True:
            # Build the filter expression for this specific day
            cayenne_exp = f'gameDate>="{query_date}" and gameDate<="{query_date}" and gameTypeId=2'

            params = {
                "isAggregate": "false",
                "sort": '[{"property":"ppTimeOnIce","direction":"DESC"}]',
                "start": start_index,
                "limit": limit,
                "cayenneExp": cayenne_exp
            }

            try:
                # Make the API request
                response = requests.get(BASE_URL, params=params)
                response.raise_for_status()  # Raise an error for bad responses (404, 500, etc.)

                data = response.json()
                players = data.get("data", [])
                total_records = data.get("total", 0)

                if not players:
                    # No more players found for this day, break the pagination loop
                    print(f"  No more records for {query_date}. (Processed {start_index} of {total_records} total)")
                    break

                print(f"  Processing records {start_index + 1}-{start_index + len(players)} of {total_records} for {query_date}...")

                # Process each player's data
                for player in players:
                    record = {}

                    # Add the date we are querying
                    record["date_"] = query_date

                    # Extract and rename the fields
                    for field in FIELDS_TO_EXTRACT:
                        # Use the remapped name if it exists, otherwise use the original field name
                        new_name = COLUMN_REMAP.get(field, field)
                        record[new_name] = player.get(field)

                    all_player_data.append(record)

                # Increment 'start' for the next page
                start_index += limit

                # Be a good citizen and pause briefly between paged requests
                time.sleep(0.5)

            except requests.exceptions.RequestException as e:
                print(f"  Error fetching data for {query_date} (start={start_index}): {e}")
                # Stop trying to paginate for this day if an error occurs
                break

        # Pause briefly between *days*
        time.sleep(1)

    # --- 4. Create DataFrame and Write to Database ---

    print("\n--- Data Fetching Complete ---")

    if not all_player_data:
        print("No new data was found for the specified date range.")
        # Still update metadata to show the window we've covered
        update_metadata(target_start_date, target_end_date)
        return False # Return False to indicate no new data was fetched

    # Convert the list of dictionaries into a pandas DataFrame
    df = pd.DataFrame(all_player_data)

    # Re-order columns to your specification
    final_columns = [
        "date_",
        "nhlplayerid",
        "skaterFullName",
        "teamAbbrevs",
        "ppTimeOnIce",
        "ppTimeOnIcePctPerGame",
        "ppAssists",
        "ppGoals"
    ]

    # Make sure all requested columns are in the DataFrame before re-ordering
    available_columns = [col for col in final_columns if col in df.columns]
    df = df[available_columns]

    print(f"Successfully fetched a total of {len(df)} player-game records.")

    # Display the first 5 rows
    print("\nData Sample (first 5 rows):")
    print(df.head())

    # --- 5. Write data to SQLite database ---
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # --- NEW LOGIC: ---
        # Get all unique dates from our new data

        # --- FIX: Drop duplicates from the dataframe *before* writing ---
        # This handles cases where the API pagination might return the same player twice.
        initial_record_count = len(df)
        df.drop_duplicates(subset=['date_', 'nhlplayerid'], keep='first', inplace=True)
        final_record_count = len(df)

        if initial_record_count != final_record_count:
            print(f"\nDropped {initial_record_count - final_record_count} duplicate records from the new data.")
        # --- END FIX ---

        dates_in_dataframe = df['date_'].unique()

        print(f"\nDeleting existing records for {len(dates_in_dataframe)} new dates to prevent duplicates...")

        # Create a placeholder string like "(?, ?, ?)"
        placeholders = ', '.join('?' for _ in dates_in_dataframe)

        # Delete all rows in the DB that match the dates we are about to insert
        cursor.execute(f"DELETE FROM powerplay_stats WHERE date_ IN ({placeholders})", tuple(dates_in_dataframe))
        conn.commit()

        print(f"Deleted {cursor.rowcount} old records for the new date range.")
        # --- END NEW LOGIC ---

        # Write the new DataFrame data to the 'powerplay_stats' table
        print(f"Writing {len(df)} new records to 'powerplay_stats' table...")
        # Using if_exists='append' because we've already cleared the date range.
        df.to_sql('powerplay_stats', conn, if_exists='append', index=False)
        conn.commit()

        print(f"Successfully wrote {len(df)} records to {DB_FILE}.")

    except sqlite3.Error as e:
        # Handle potential "UNIQUE constraint failed" errors if the cleanup logic failed
        # This "except" block should ideally not be hit anymore, but we'll keep it as a safeguard.
        if "UNIQUE constraint failed" in str(e):
            print(f"Note: Some records may have already existed in the database.")
        else:
            print(f"An error occurred while writing to the database: {e}")
    finally:
        if conn:
            conn.close()

    # --- 6. Update Metadata ---
    # Update metadata to reflect the new 7-day window
    update_metadata(target_start_date, target_end_date)
    return True # Return True to indicate new data was fetched and written


def fetch_team_stats_summary():
    """
    Fetches Team PP%, PK%, GF, GA, SF, and SA from the NHL Stats API and stores them
    in the 'team_stats_summary' table.
    """
    print("\n--- Fetching Team PP% and PK% ---")

    # 1. Construct the URL and Parameters
    # Note: We dynamically set the seasonId based on the current year logic if needed,
    # but for now we use the one from your URL (20252026).
    API_URL = "https://api.nhle.com/stats/rest/en/team/summary"

    params = {
        "isAggregate": "false",
        "isGame": "false",
        "start": 0,
        "limit": 50,
        "cayenneExp": "seasonId=20252026 and gameTypeId=2"
    }

    all_team_data = []

    try:
        response = requests.get(API_URL, params=params)
        response.raise_for_status()

        data = response.json()
        teams_list = data.get("data", [])

        if not teams_list:
            print("  No team stats data found in API response.")
            return

        # 2. Process the data
        for team in teams_list:
            franchise_name = team.get("teamFullName")
            team_tricode = FRANCHISE_TO_TRICODE_MAP.get(franchise_name)
            pp_pct = team.get("powerPlayPct")
            pk_pct = team.get("penaltyKillPct")
            gf_gm = team.get("goalsForPerGame")
            ga_gm = team.get("goalsAgainstPerGame")
            sogf_gm = team.get("shotsForPerGame")
            soga_gm = team.get("shotsAgainstPerGame")


            if team_tricode:
                all_team_data.append((team_tricode, pp_pct, pk_pct, gf_gm, ga_gm, sogf_gm, soga_gm))

    except requests.exceptions.RequestException as e:
        print(f"  Error fetching team stats: {e}")
        return

    # 3. Write to Database
    conn = None
    if not all_team_data:
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        print(f"  Clearing 'team_stats_summary' table...")
        cursor.execute("DELETE FROM team_stats_summary")

        print(f"  Inserting {len(all_team_data)} team records (PP% / PK%)...")
        cursor.executemany('''
        INSERT INTO team_stats_summary (team_tricode, pp_pct, pk_pct, gf_gm, ga_gm, sogf_gm, soga_gm)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', all_team_data)

        conn.commit()
        print("  Successfully updated 'team_stats_summary' table.")

    except sqlite3.Error as e:
        print(f"  Database error: {e}")
    finally:
        if conn:
            conn.close()


def fetch_team_stats_weekly():
    """
    Fetches Team PP% and PK% for the last 7 days (7 days ago to yesterday)
    and stores them in the 'team_stats_weekly' table.
    """
    print("\n--- Fetching Weekly Team PP% and PK% (Last 7 Days) ---")

    # 1. Calculate Date Range (7 days ago to yesterday)
    today = date.today()
    end_date = today - timedelta(days=1)
    start_date = today - timedelta(days=7)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"  Querying for date range: {start_str} to {end_str}")

    # 2. Construct the URL and Parameters
    API_URL = "https://api.nhle.com/stats/rest/en/team/summary"

    params = {
        # We set isAggregate=true to get ONE row per team, summing up all
        # stats within the date range.
        "isAggregate": "true",
        "isGame": "false",
        "start": 0,
        "limit": 50,
        # Filter by gameDate (inclusive) and gameType
        "cayenneExp": f'gameDate>="{start_str}" and gameDate<="{end_str}" and gameTypeId=2'
    }

    all_team_data = []

    try:
        response = requests.get(API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        teams_list = data.get("data", [])
        if not teams_list:
            print("  No weekly team stats data found in API response.")
            return

        # 3. Process the data
        for team in teams_list:
            franchise_name = team.get("franchiseName")
            team_tricode = FRANCHISE_TO_TRICODE_MAP.get(franchise_name)
            pp_pct = team.get("powerPlayPct")
            pk_pct = team.get("penaltyKillPct")
            gf_gm = team.get("goalsForPerGame")
            ga_gm = team.get("goalsAgainstPerGame")
            sogf_gm = team.get("shotsForPerGame")
            soga_gm = team.get("shotsAgainstPerGame")

            if team_tricode:
                all_team_data.append((team_tricode, pp_pct, pk_pct, gf_gm, ga_gm, sogf_gm, soga_gm))

    except requests.exceptions.RequestException as e:
        print(f"  Error fetching weekly team stats: {e}")
        return

    # 4. Write to Database
    conn = None
    if not all_team_data:
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        print(f"  Clearing 'team_stats_weekly' table...")
        cursor.execute("DELETE FROM team_stats_weekly")

        print(f"  Inserting {len(all_team_data)} weekly team records (PP% / PK%)...")
        cursor.executemany('''
        INSERT INTO team_stats_weekly (team_tricode, pp_pct_weekly, pk_pct_weekly, gf_gm_weekly, ga_gm_weekly, sogf_gm_weekly, soga_gm_weekly)
        VALUES (?, ?, ?, ?, ?, ?, ? )
        ''', all_team_data)

        conn.commit()
        print("  Successfully updated 'team_stats_weekly' table.")

    except sqlite3.Error as e:
        print(f"  Database error: {e}")
    finally:
        if conn:
            conn.close()


def copy_team_stats_to_projections():
    """
    Copies the 'team_stats_summary' table from special_teams.db
    into projections.db as a new, separate table.
    """
    print("\n--- Copying 'team_stats_summary' table to projections.db ---")
    conn = None
    try:
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)
        cursor = conn.cursor()

        print(f"  Attaching Special Teams DB: {DB_FILE}")
        cursor.execute(f"ATTACH DATABASE '{DB_FILE}' AS special_teams_db")

        print("  Reading 'team_stats_summary' from special_teams_db...")
        df_stats = pd.read_sql_query("SELECT * FROM special_teams_db.team_stats_summary", conn)

        if not df_stats.empty:
            print(f"  Writing {len(df_stats)} records to 'team_stats_summary' table in {PROJECTIONS_DB_FILE}...")
            df_stats.to_sql('team_stats_summary',
                            conn,
                            if_exists='replace',
                            index=False,
                            dtype={'team_tricode': 'TEXT', 'pp_pct': 'REAL', 'pk_pct': 'REAL', 'gf_gm': 'REAL', 'ga_gm': 'REAL', 'sogf_gm': 'REAL', 'soga_gm': 'REAL'})
            conn.commit()
            print("  Successfully copied 'team_stats_summary' table.")
        else:
            print("  Warning: Source table was empty.")

        cursor.execute("DETACH DATABASE special_teams_db")

    except Exception as e:
        print(f"  Error during copy: {e}", file=sys.stderr)
        try: cursor.execute("DETACH DATABASE special_teams_db")
        except: pass
    finally:
        if conn: conn.close()


def copy_team_stats_weekly_to_projections():
    """
    Copies the 'team_stats_weekly' table from special_teams.db
    into projections.db as a new, separate table.
    """
    print("\n--- Copying 'team_stats_weekly' table to projections.db ---")
    conn = None
    try:
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)
        cursor = conn.cursor()

        print(f"  Attaching Special Teams DB: {DB_FILE}")
        cursor.execute(f"ATTACH DATABASE '{DB_FILE}' AS special_teams_db")

        print("  Reading 'team_stats_weekly' from special_teams_db...")
        df_stats = pd.read_sql_query("SELECT * FROM special_teams_db.team_stats_weekly", conn)

        if not df_stats.empty:
            print(f"  Writing {len(df_stats)} records to 'team_stats_weekly' table in {PROJECTIONS_DB_FILE}...")
            df_stats.to_sql('team_stats_weekly',
                            conn,
                            if_exists='replace',
                            index=False,
                            dtype={'team_tricode': 'TEXT', 'pp_pct_weekly': 'REAL', 'pk_pct_weekly': 'REAL', 'gf_gm_weekly': 'REAL', 'ga_gm_weekly': 'REAL', 'sogf_gm_weekly': 'REAL', 'soga_gm_weekly': 'REAL'})
            conn.commit()
            print("  Successfully copied 'team_stats_weekly' table.")
        else:
            print("  Warning: Source 'team_stats_weekly' table was empty.")

        cursor.execute("DETACH DATABASE special_teams_db")

    except Exception as e:
        print(f"  Error during copy: {e}", file=sys.stderr)
        try: cursor.execute("DETACH DATABASE special_teams_db")
        except: pass
    finally:
        if conn: conn.close()



# --- NEW FUNCTION (MOVED FROM create_projection_db.py) ---
def join_special_teams_data():
    """
    Joins data from last_game_pp and last_week_pp (from special_teams.db)
    into the main projections table (in projections.db).
    """
    print("\n--- Joining Special Teams (Powerplay) Data into projections.db ---")
    conn = None
    try:
        # 1. Connect to the MAIN projections.db
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)
        cursor = conn.cursor()

        # 2. Attach the special_teams.db
        print(f"Attaching Special Teams DB: {DB_FILE}")
        cursor.execute(f"ATTACH DATABASE '{DB_FILE}' AS special_teams_db")

        # 3. Load the current 'projections' table from projections.db
        df_proj = pd.read_sql_query("SELECT * FROM projections", conn)
        if df_proj.empty:
            print("Error: 'projections' table is empty. Cannot join data.")
            print("Please run the full create_projection_db.py script first.")
            return
        print(f"Loaded {len(df_proj)} players from 'projections' table.")

        # 4. Load 'last_game_pp' data from special_teams.db
        lg_cols_to_load = [
            "nhlplayerid",
            "ppTimeOnIce",
            "ppTimeOnIcePctPerGame",
            "ppAssists",
            "ppGoals"
        ]
        lg_query = f"SELECT {', '.join(lg_cols_to_load)} FROM special_teams_db.last_game_pp"
        df_last_game = pd.read_sql_query(lg_query, conn)
        print(f"Loaded {len(df_last_game)} rows from 'last_game_pp'.")

        # Rename columns with "lg_" prefix
        df_last_game = df_last_game.rename(columns={
            "ppTimeOnIce": "lg_ppTimeOnIce",
            "ppTimeOnIcePctPerGame": "lg_ppTimeOnIcePctPerGame",
            "ppAssists": "lg_ppAssists",
            "ppGoals": "lg_ppGoals"
        })

        # 5. Load 'last_week_pp' data from special_teams.db
        lw_cols_to_load = [
            "nhlplayerid",
            "avg_ppTimeOnIce",
            "avg_ppTimeOnIcePctPerGame",
            "total_ppAssists",
            "total_ppGoals",
            "player_games_played",
            "team_games_played"
        ]
        lw_query = f"SELECT {', '.join(lw_cols_to_load)} FROM special_teams_db.last_week_pp"
        df_last_week = pd.read_sql_query(lw_query, conn)
        print(f"Loaded {len(df_last_week)} rows from 'last_week_pp'.")

        # 6. Merge the dataframes
        # First, clean up projections table from any old pp columns
        lg_cols_to_drop = list(df_last_game.columns.drop('nhlplayerid'))
        lw_cols_to_drop = list(df_last_week.columns.drop('nhlplayerid'))
        all_cols_to_drop = lg_cols_to_drop + lw_cols_to_drop

        existing_cols_to_drop = [col for col in all_cols_to_drop if col in df_proj.columns]
        if existing_cols_to_drop:
            print(f"Dropping {len(existing_cols_to_drop)} old special teams columns...")
            df_proj = df_proj.drop(columns=existing_cols_to_drop)

        # Merge last game data (on 'nhlplayerid')
        df_final = pd.merge(df_proj, df_last_game, on='nhlplayerid', how='left')
        print(f"Merged 'last_game_pp' data. DataFrame shape: {df_final.shape}")

        # Merge last week data (on 'nhlplayerid')
        df_final = pd.merge(df_final, df_last_week, on='nhlplayerid', how='left')
        print(f"Merged 'last_week_pp' data. DataFrame shape: {df_final.shape}")

        # 7. Save back to the 'projections' table
        print(f"Saving {len(df_final)} players back to 'projections' table...")

        # Re-apply Int64 types to ensure INTEGER columns
        if 'nhlplayerid' in df_final.columns:
            df_final['nhlplayerid'] = pd.to_numeric(df_final['nhlplayerid'], errors='coerce').fillna(pd.NA).astype('Int64')
        if 'player_id' in df_final.columns:
             df_final['player_id'] = pd.to_numeric(df_final['player_id'], errors='coerce').fillna(pd.NA).astype('Int64')

        df_final.to_sql('projections',
                        conn,
                        if_exists='replace',
                        index=False,
                        dtype={'nhlplayerid': 'INTEGER', 'player_id': 'INTEGER'})

        # 8. Re-create the index (to_sql replaces it)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_normalized_name_projections ON projections(player_name_normalized)')

        # 9. Detach the special_teams.db
        cursor.execute("DETACH DATABASE special_teams_db")

        # 10. Commit changes to projections.db
        conn.commit()
        print("Successfully joined special teams data and detached DB.")

    except sqlite3.OperationalError as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        print(f"Please ensure '{PROJECTIONS_DB_FILE}' exists and '{DB_FILE}' exists.", file=sys.stderr)
        try:
            cursor.execute("DETACH DATABASE special_teams_db")
        except: pass
    except Exception as e:
        print(f"An error occurred during special teams join: {e}", file=sys.stderr)
        try:
            cursor.execute("DETACH DATABASE special_teams_db")
        except: pass
    finally:
        if conn:
            conn.close()
# --- END NEW FUNCTION ---


def fetch_team_standings():
    """
    Fetches the current team standings, clears the 'team_standings' table,
    and inserts the new data.
    """
    print("\n--- Fetching Team Standings ---")

    # 1. Get today's date for the API URL
    today_str = date.today().strftime("%Y-%m-%d")
    API_URL = f"https://api-web.nhle.com/v1/standings/{today_str}"

    all_standings_data = []

    # 2. Fetch data from the API
    try:
        response = requests.get(API_URL)
        response.raise_for_status()  # Raise an error for bad responses

        data = response.json()
        standings_list = data.get("standings", [])

        if not standings_list:
            print("  No standings data found in API response.")
            return

        # 3. Process the data
        for team in standings_list:
            team_tricode = team.get("teamAbbrev", {}).get("default")
            point_pct_raw = team.get("pointPctg")

            # --- MODIFIED SECTION ---
            goals_against = team.get("goalAgainst")
            games_played = team.get("gamesPlayed") # This value is already being pulled

            ga_per_game = None
            # Check for valid data and games_played > 0 to avoid ZeroDivisionError
            if isinstance(goals_against, (int, float)) and isinstance(games_played, int) and games_played > 0:
                ga_per_game = round(goals_against / games_played, 2)
            # --- END MODIFIED SECTION ---

            # Format point_pct
            point_pct_formatted = None
            if isinstance(point_pct_raw, (int, float)):
                # Format to 3 decimal places (e.g., "0.794")
                formatted_str = f"{point_pct_raw:.3f}"
                # Lop off the leading "0" to get ".794"
                if formatted_str.startswith("0"):
                    point_pct_formatted = formatted_str[1:]
                else:
                    # Handle cases like 1.000
                    point_pct_formatted = formatted_str

            if team_tricode:
                all_standings_data.append((
                    team_tricode,
                    point_pct_formatted,
                    ga_per_game,
                    games_played  # <-- ADDED
                ))

    except requests.exceptions.RequestException as e:
        print(f"  Error fetching team standings from {API_URL}: {e}")
        return # Stop execution if API call fails
    except Exception as e:
        print(f"  An error occurred processing standings data: {e}")
        return

    # 4. Write data to SQLite database
    conn = None
    if not all_standings_data:
        print("  No processed standings data to write.")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Clear the table first
        print(f"  Clearing 'team_standings' table...")
        cursor.execute("DELETE FROM team_standings")

        # Insert all new data
        print(f"  Inserting {len(all_standings_data)} new team records...")
        # --- MODIFIED ---
        cursor.executemany('''
        INSERT INTO team_standings (team_tricode, point_pct, goals_against_per_game, games_played)
        VALUES (?, ?, ?, ?)
        ''', all_standings_data)
        # --- END MODIFIED ---

        conn.commit()
        print("  Successfully updated 'team_standings' table.")

    except sqlite3.Error as e:
        print(f"  An error occurred while writing to 'team_standings': {e}")
    finally:
        if conn:
            conn.close()

    # 4. Write data to SQLite database
    conn = None
    if not all_standings_data:
        print("  No processed standings data to write.")
        return




def fetch_and_update_scoring_to_date():
    """
    Fetches the current season's to-date summary stats for all skaters
    from the NHL API, calculates per-game stats, and writes to
    the 'scoring_to_date' table in the special_teams.db.
    """
    print("\n--- Starting NHL To-Date Skater Stats Fetch ---")

    # Base URL for the skater summary report
    base_url = "https://api.nhle.com/stats/rest/en/skater/summary"

    all_players_data = []
    start = 0
    limit = 100 # Fetch 100 players per page

    # Get the current season (e.g., 20252026)
    # Assumes the script is run during the season
    current_year = date.today().year
    season_end_year = current_year if date.today().month < 7 else current_year + 1
    season_start_year = season_end_year - 1
    season_id = f"{season_start_year}{season_end_year}"
    print(f"Fetching data for season: {season_id}")

    while True:
        try:
            # Parameters based on the user's URL
            params = {
                "isAggregate": "false",
                "cayenneExp": f"gameTypeId=2 and seasonId={season_id}",
                "sort": '[{"property":"points","direction":"DESC"}]',
                "start": start,
                "limit": limit
            }

            response = requests.get(base_url, params=params)
            response.raise_for_status() # Raise an exception for bad status codes

            data = response.json()
            players_list = data.get('data', [])

            if not players_list:
                # No more players found, break the loop
                print(f"Finished fetching. Total players retrieved: {len(all_players_data)}")
                break

            all_players_data.extend(players_list)
            print(f"Retrieved {len(players_list)} players... (Total: {len(all_players_data)})")

            # Increment for the next page
            start += limit

            # Be polite to the API
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from NHL API: {e}", file=sys.stderr)
            return
        except Exception as e:
            print(f"An error occurred: {e}", file=sys.stderr)
            return

    if not all_players_data:
        print("No player data was fetched. Exiting function.")
        return

    # --- Process Data with Pandas ---
    try:
        df = pd.DataFrame(all_players_data)

        # 1. Define columns to keep
        # We need 'gamesPlayed' for calculation, even if not in final user list
        required_cols = [
            'playerId', 'skaterFullName', 'teamAbbrevs', 'gamesPlayed',
            'goals', 'assists', 'points', 'plusMinus', 'penaltyMinutes',
            'ppGoals', 'ppPoints', 'shootingPct', 'timeOnIcePerGame', 'shots'
        ]

        # Filter for only columns that exist (in case API changes)
        existing_cols = [col for col in required_cols if col in df.columns]
        df = df[existing_cols]

        # 2. Handle 'gamesPlayed' == 0 to avoid ZeroDivisionError
        # Convert to numeric, coercing errors to NaN, then fill NaNs with 0
        df['gamesPlayed'] = pd.to_numeric(df['gamesPlayed'], errors='coerce').fillna(0)

        # 3. Create 'ppAssists'
        # Convert ppPoints and ppGoals to numeric first
        df['ppPoints'] = pd.to_numeric(df['ppPoints'], errors='coerce').fillna(0)
        df['ppGoals'] = pd.to_numeric(df['ppGoals'], errors='coerce').fillna(0)
        df['ppAssists'] = df['ppPoints'] - df['ppGoals']

        # 4. List of columns to convert to per-game stats
        cols_to_divide = [
            'goals', 'assists', 'points', 'plusMinus',
            'penaltyMinutes', 'ppGoals', 'ppPoints', 'ppAssists', 'timeOnIcePerGame', 'shots'
        ]

        # 5. Calculate per-game stats safely
        for col in cols_to_divide:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                # Use np.where to avoid division by zero
                df[col] = np.where(
                    df['gamesPlayed'] > 0,
                    df[col] / df['gamesPlayed'],
                    0
                )

        # 6. Final column selection and renaming
        final_cols = [
            'playerId', 'skaterFullName', 'teamAbbrevs', 'gamesPlayed', 'goals', 'assists',
            'points', 'plusMinus', 'penaltyMinutes', 'ppGoals', 'ppAssists',
            'ppPoints', 'shootingPct', 'timeOnIcePerGame', 'shots'
        ]

        # Ensure all requested final columns exist
        df_final = df[[col for col in final_cols if col in df.columns]]

        # Rename playerId to nhlplayerid
        df_final = df_final.rename(columns={'playerId': 'nhlplayerid'})

        # 7. Write to database
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            print(f"Writing {len(df_final)} records to 'scoring_to_date' table in {DB_FILE}...")

            # 'replace' will drop the table if it exists and create a new one
            df_final.to_sql('scoring_to_date', conn, if_exists='replace', index=False)

            print("Successfully wrote to-date stats to database.")

        except sqlite3.Error as e:
            print(f"Database error while writing 'scoring_to_date': {e}", file=sys.stderr)
        except Exception as e:
            print(f"An error occurred during database write: {e}", file=sys.stderr)
        finally:
            if conn:
                conn.close()

    except Exception as e:
        print(f"An error occurred during data processing: {e}", file=sys.stderr)


def fetch_and_update_bangers_stats():
    """
    Fetches the current season's 'scoringpergame' report for all skaters
    from the NHL API, selects 'banger' stats, and writes them to
    the 'bangers_to_date' table in special_teams.db.
    """
    print("\n--- Starting NHL 'Bangers' Stats Fetch (Per Game) ---")

    # Base URL for the skater scoringpergame report
    base_url = "https://api.nhle.com/stats/rest/en/skater/scoringpergame"

    all_players_data = []
    start = 0
    limit = 100 # Fetch 100 players per page

    # Get the current season (e.g., 20252026)
    current_year = date.today().year
    season_end_year = current_year if date.today().month < 7 else current_year + 1
    season_start_year = season_end_year - 1
    season_id = f"{season_start_year}{season_end_year}"
    print(f"Fetching data for season: {season_id}")

    while True:
        try:
            # Parameters for the scoringpergame endpoint
            params = {
                "isAggregate": "false",
                "cayenneExp": f"gameTypeId=2 and seasonId={season_id}",
                "sort": '[{"property":"hitsPerGame","direction":"DESC"}]', # Sort by hits
                "start": start,
                "limit": limit
            }

            response = requests.get(base_url, params=params)
            response.raise_for_status() # Raise an exception for bad status codes

            data = response.json()
            players_list = data.get('data', [])

            if not players_list:
                # No more players found, break the loop
                print(f"Finished fetching. Total players retrieved: {len(all_players_data)}")
                break

            all_players_data.extend(players_list)
            print(f"Retrieved {len(players_list)} players... (Total: {len(all_players_data)})")

            # Increment for the next page
            start += limit

            # Be polite to the API
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from NHL API: {e}", file=sys.stderr)
            return
        except Exception as e:
            print(f"An error occurred: {e}", file=sys.stderr)
            return

    if not all_players_data:
        print("No player data was fetched for bangers stats. Exiting function.")
        return

    # --- Process Data with Pandas ---
    try:
        df = pd.DataFrame(all_players_data)

        # 1. Define columns to keep
        required_cols = [
            'playerId', 'skaterFullName', 'teamAbbrevs',
            'blocksPerGame', 'hitsPerGame'
        ]

        # Filter for only columns that exist (in case API changes)
        existing_cols = [col for col in required_cols if col in df.columns]
        df_final = df[existing_cols]

        # 2. Rename playerId to nhlplayerid
        df_final = df_final.rename(columns={'playerId': 'nhlplayerid'})

        # 3. Write to database
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            print(f"Writing {len(df_final)} records to 'bangers_to_date' table in {DB_FILE}...")

            # 'replace' will drop the table if it exists and create a new one
            df_final.to_sql('bangers_to_date', conn, if_exists='replace', index=False)

            print("Successfully wrote bangers stats to database.")

        except sqlite3.Error as e:
            print(f"Database error while writing 'bangers_to_date': {e}", file=sys.stderr)
        except Exception as e:
            print(f"An error occurred during database write: {e}", file=sys.stderr)
        finally:
            if conn:
                conn.close()

    except Exception as e:
        print(f"An error occurred during data processing: {e}", file=sys.stderr)


def fetch_and_update_goalie_stats():
    """
    Fetches the current season's 'summary' report for all goalies
    from the NHL API, calculates per-game stats, joins team games_played,
    calculates startpct, and writes them to the 'goalie_to_date'
    table in special_teams.db.
    """
    print("\n--- Starting NHL Goalie Stats Fetch (Per Game) ---")

    # Base URL for the goalie summary report
    base_url = "https://api.nhle.com/stats/rest/en/goalie/summary"

    all_goalie_data = []
    start = 0
    limit = 100 # Fetch 100 goalies per page

    # Get the current season (e.g., 20252026)
    current_year = date.today().year
    season_end_year = current_year if date.today().month < 7 else current_year + 1
    season_start_year = season_end_year - 1
    season_id = f"{season_start_year}{season_end_year}"
    print(f"Fetching goalie data for season: {season_id}")

    while True:
        try:
            # Parameters for the goalie summary endpoint
            params = {
                "isAggregate": "false",
                "cayenneExp": f"gameTypeId=2 and seasonId={season_id}",
                "sort": '[{"property":"wins","direction":"DESC"}]', # Sort by wins
                "start": start,
                "limit": limit
            }

            response = requests.get(base_url, params=params)
            response.raise_for_status() # Raise an exception for bad status codes

            data = response.json()
            goalie_list = data.get('data', [])

            if not goalie_list:
                # No more goalies found, break the loop
                print(f"Finished fetching. Total goalies retrieved: {len(all_goalie_data)}")
                break

            all_goalie_data.extend(goalie_list)
            print(f"Retrieved {len(goalie_list)} goalies... (Total: {len(all_goalie_data)})")

            # Increment for the next page
            start += limit

            # Be polite to the API
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from NHL API: {e}", file=sys.stderr)
            return
        except Exception as e:
            print(f"An error occurred: {e}", file=sys.stderr)
            return

    if not all_goalie_data:
        print("No goalie data was fetched. Exiting function.")
        return

    # --- Process Data with Pandas ---
    try:
        df = pd.DataFrame(all_goalie_data)

        # 1. Define columns to keep
        required_cols = [
            'playerId', 'goalieFullName', 'teamAbbrevs', 'gamesStarted', 'gamesPlayed',
            'goalsAgainstAverage', 'losses', 'savePct', 'saves', 'shotsAgainst',
            'shutouts', 'wins', 'goalsAgainst'
        ]

        # Filter for only columns that exist (in case API changes)
        existing_cols = [col for col in required_cols if col in df.columns]
        df_final = df[existing_cols].copy() # Use .copy() to avoid SettingWithCopyWarning

        # 2. Ensure gamesPlayed is numeric and handle division by zero
        df_final['gamesPlayed'] = pd.to_numeric(df_final['gamesPlayed'], errors='coerce').fillna(0)

        # 3. Calculate new/updated columns
        # Added 'wins' to this list to ensure numeric conversion before we split it
        stats_to_convert = ['saves', 'shotsAgainst', 'wins', 'losses', 'shutouts', 'gamesStarted', 'goalsAgainst']
        for col in stats_to_convert:
            if col in df_final.columns:
                df_final[col] = pd.to_numeric(df_final[col], errors='coerce').fillna(0)

        # --- CHANGED: Logic for Win Total vs Win Pct ---

        # Save the raw win count into a new column 'win_total'
        df_final['win_total'] = df_final['wins']

        # Overwrite 'wins' with the percentage (Win % Per Game)
        df_final['wins'] = np.where(
            df_final['gamesPlayed'] > 0,
            df_final['win_total'] / df_final['gamesPlayed'],
            0
        )

        # Calculate saves per game and replace 'saves'
        df_final['saves'] = np.where(
            df_final['gamesPlayed'] > 0,
            df_final['saves'] / df_final['gamesPlayed'],
            0
        )

        # Calculate shotsAgainst per game and replace 'shotsAgainst'
        df_final['shotsAgainst'] = np.where(
            df_final['gamesPlayed'] > 0,
            df_final['shotsAgainst'] / df_final['gamesPlayed'],
            0
        )

        # Calculate goalsAgainst per game and replace 'goalsAgainst'
        df_final['goalsAgainst'] = np.where(
            df_final['gamesPlayed'] > 0,
            df_final['goalsAgainst'] / df_final['gamesPlayed'],
            0
        )

        # 4. Rename playerId to nhlplayerid
        df_final = df_final.rename(columns={'playerId': 'nhlplayerid'})

        # 5. Connect to DB, join with standings, and write
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)

            # --- NEW: Read team_standings table ---
            print("  Reading 'team_standings' for join...")
            # Read only the columns we need and rename games_played to avoid conflict
            df_standings = pd.read_sql_query(
                "SELECT team_tricode, games_played AS team_games_played FROM team_standings",
                conn
            )

            if df_standings.empty:
                print("  Warning: 'team_standings' table is empty. 'startpct' will be 0.")
                # Create an empty df with columns to prevent merge error
                df_standings = pd.DataFrame(columns=['team_tricode', 'team_games_played'])

            # --- NEW: Merge with goalie data ---
            # Use 'left' merge to keep all goalies
            df_final = pd.merge(
                df_final,
                df_standings,
                left_on='teamAbbrevs',
                right_on='team_tricode',
                how='left'
            )

            # --- NEW: Calculate startpct ---
            # Ensure team_games_played is numeric and fill NaNs (from failed merges) with 0
            df_final['team_games_played'] = pd.to_numeric(df_final['team_games_played'], errors='coerce').fillna(0)

            # Use np.where for safe division (gamesStarted was already converted)
            df_final['startpct'] = np.where(
                df_final['team_games_played'] > 0,
                df_final['gamesStarted'] / df_final['team_games_played'],
                0  # Set to 0 if team_games_played is 0
            )

            # --- NEW: Clean up columns from merge ---
            # Drop the extra columns we joined on and used for calculation
            df_final = df_final.drop(columns=['team_tricode', 'team_games_played'], errors='ignore')

            # --- END NEW ---

            print(f"Writing {len(df_final)} records to 'goalie_to_date' table in {DB_FILE}...")

            # 'replace' will drop the table if it exists and create a new one
            # The new table will automatically include the 'startpct' and 'win_total' columns
            df_final.to_sql('goalie_to_date', conn, if_exists='replace', index=False)

            print("Successfully wrote goalie stats to database.")

        except sqlite3.Error as e:
            print(f"Database error while writing 'goalie_to_date': {e}", file=sys.stderr)
        except Exception as e:
            print(f"An error occurred during database write: {e}", file=sys.stderr)
        finally:
            if conn:
                conn.close()

    except Exception as e:
        print(f"An error occurred during data processing: {e}", file=sys.stderr)



def copy_standings_to_projections():
    """
    Copies the 'team_standings' table from special_teams.db
    into projections.db as a new, separate table.
    """
    print("\n--- Copying 'team_standings' table to projections.db ---")
    conn = None
    try:
        # 1. Connect to the MAIN projections.db
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)
        cursor = conn.cursor()

        # 2. Attach the special_teams.db
        print(f"  Attaching Special Teams DB: {DB_FILE}")
        cursor.execute(f"ATTACH DATABASE '{DB_FILE}' AS special_teams_db")

        # 3. Load 'team_standings' data from special_teams.db into a DataFrame
        print("  Reading 'team_standings' from special_teams_db...")
        df_standings = pd.read_sql_query("SELECT * FROM special_teams_db.team_standings", conn)

        if df_standings.empty:
            print("  Warning: 'team_standings' in special_teams.db is empty. An empty table will be created.")

        # 4. Write this DataFrame to a new table in projections.db
        print(f"  Writing {len(df_standings)} records to 'team_standings' table in {PROJECTIONS_DB_FILE}...")

        # --- MODIFIED ---
        df_standings.to_sql('team_standings',
                            conn,
                            if_exists='replace',
                            index=False,
                            dtype={'team_tricode': 'TEXT', 'point_pct': 'TEXT', 'goals_against_per_game': 'REAL', 'games_played': 'INTEGER'})
        # --- END MODIFIED ---

        # 5. Detach the special_teams.db
        cursor.execute("DETACH DATABASE special_teams_db")

        # 6. Commit changes to projections.db
        conn.commit()
        print("  Successfully copied 'team_standings' table and detached DB.")

    except sqlite3.OperationalError as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        print(f"Please ensure '{PROJECTIONS_DB_FILE}' and '{DB_FILE}' exist.", file=sys.stderr)
        try:
            cursor.execute("DETACH DATABASE special_teams_db")
        except: pass
    except Exception as e:
        print(f"An error occurred during table copy: {e}", file=sys.stderr)
        try:
            cursor.execute("DETACH DATABASE special_teams_db")
        except: pass
    finally:
        if conn:
            conn.close()


def create_stats_to_date_table():
    """
    Connects to projections.db and special_teams.db.
    Joins 'projections' table with 'scoring_to_date', 'bangers_to_date',
    and 'goalie_to_date' on 'nhlplayerid'.
    Saves the result as a new table 'stats_to_date' in projections.db.
    """
    print(f"\n--- Creating 'stats_to_date' table in {PROJECTIONS_DB_FILE} ---")
    conn = None
    try:
        # 1. Connect to the MAIN projections.db
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)
        cursor = conn.cursor()

        # 2. Attach the special_teams.db
        print(f"  Attaching Special Teams DB: {DB_FILE}")
        cursor.execute(f"ATTACH DATABASE '{DB_FILE}' AS st_db")

        # 3. Load all source tables into DataFrames
        print("  Reading source tables...")

        # --- Projections (Base Table) ---
        df_proj = pd.read_sql_query("SELECT * FROM projections", conn)
        if df_proj.empty:
            print(f"  Error: 'projections' table in {PROJECTIONS_DB_FILE} is empty. Aborting.")
            cursor.execute("DETACH DATABASE st_db")
            return

        # --- Scoring ---
        df_scoring = pd.read_sql_query("SELECT * FROM st_db.scoring_to_date", conn)

        # --- Bangers ---
        df_bangers = pd.read_sql_query("SELECT * FROM st_db.bangers_to_date", conn)

        # --- Goalies ---
        df_goalie = pd.read_sql_query("SELECT * FROM st_db.goalie_to_date", conn)

        # 4. Define columns and rename mappings

        # --- Projections Columns ---
        proj_cols = [
            'nhlplayerid', 'player_name_normalized', 'player_name', 'team',
            'age', 'player_id', 'positions', 'status', 'lg_ppTimeOnIce',
            'lg_ppTimeOnIcePctPerGame', 'lg_ppAssists', 'lg_ppGoals', 'avg_ppTimeOnIce',
            'avg_ppTimeOnIcePctPerGame', 'total_ppAssists', 'total_ppGoals',
            'player_games_played', 'team_games_played'
        ]
        # Ensure we only select columns that actually exist in df_proj
        proj_cols_exist = [col for col in proj_cols if col in df_proj.columns]
        df_proj_selected = df_proj[proj_cols_exist].copy()

        # --- Scoring Columns & Renames ---
        scoring_rename_map = {
            'nhlplayerid': 'nhlplayerid', # Keep the join key
            'gamesPlayed': 'GPskater',
            'goals': 'G',
            'assists': 'A',
            'points': 'P',
            'plusMinus': 'plus_minus',
            'penaltyMinutes': 'PIM',
            'ppGoals': 'PPG',
            'ppAssists': 'PPA',
            'ppPoints': 'PPP',
            'shootingPct': 'shootingPct',
            'timeOnIcePerGame': 'timeOnIcePerGame',
            'shots': 'SOG'
        }
        scoring_cols_exist = [col for col in scoring_rename_map.keys() if col in df_scoring.columns]
        df_scoring_selected = df_scoring[scoring_cols_exist].rename(columns=scoring_rename_map)

        # --- Bangers Columns & Renames ---
        bangers_rename_map = {
            'nhlplayerid': 'nhlplayerid', # Keep the join key
            'blocksPerGame': 'BLK',
            'hitsPerGame': 'HIT'
        }
        bangers_cols_exist = [col for col in bangers_rename_map.keys() if col in df_bangers.columns]
        df_bangers_selected = df_bangers[bangers_cols_exist].rename(columns=bangers_rename_map)

        # --- Goalie Columns & Renames ---
        goalie_rename_map = {
            'nhlplayerid': 'nhlplayerid', # Keep the join key
            'gamesStarted': 'GS',
            'gamesPlayed': 'GP',
            'goalsAgainstAverage': 'GAA',
            'losses': 'L',
            'savePct': 'SVpct',
            'saves': 'SV',
            'shotsAgainst': 'SA',
            'shutouts': 'SHO',
            'wins': 'W',            # This is now the percentage
            'win_total': 'win_total', # This is the new raw count
            'goalsAgainst': 'GA',
            'startpct': 'startpct'
        }
        # Removed 'winpct' from rename map as requested

        goalie_cols_exist = [col for col in goalie_rename_map.keys() if col in df_goalie.columns]
        df_goalie_selected = df_goalie[goalie_cols_exist].rename(columns=goalie_rename_map)

        # 5. Perform the merges
        print("  Joining tables...")

        # Start with the base projections table
        df_merged = df_proj_selected

        # Merge scoring
        if not df_scoring_selected.empty:
            # Drop join key if it's not the first merge
            cols_to_merge = df_scoring_selected.columns
            df_merged = pd.merge(df_merged, df_scoring_selected[cols_to_merge], on='nhlplayerid', how='left')

        # Merge bangers
        if not df_bangers_selected.empty:
            cols_to_merge = df_bangers_selected.columns
            df_merged = pd.merge(df_merged, df_bangers_selected[cols_to_merge], on='nhlplayerid', how='left')

        # Merge goalies
        if not df_goalie_selected.empty:
            cols_to_merge = df_goalie_selected.columns
            df_merged = pd.merge(df_merged, df_goalie_selected[cols_to_merge], on='nhlplayerid', how='left')

        # 6. Write the final table to projections.db
        print(f"  Writing {len(df_merged)} records to 'stats_to_date'...")
        df_merged.to_sql(
            'stats_to_date',
            conn,
            if_exists='replace',
            index=False,
            dtype={'nhlplayerid': 'INTEGER', 'player_id': 'INTEGER'} # Ensure key types
        )

        print("  Successfully created 'stats_to_date' table.")

        # 7. Detach the special_teams.db
        cursor.execute("DETACH DATABASE st_db")
        conn.commit()
        print("  Detached special_teams.db.")

    except sqlite3.OperationalError as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        try: cursor.execute("DETACH DATABASE st_db")
        except: pass
    except Exception as e:
        print(f"An error occurred during 'stats_to_date' creation: {e}", file=sys.stderr)
        try: cursor.execute("DETACH DATABASE st_db")
        except: pass
    finally:
        if conn:
            conn.close()


def calculate_and_save_to_date_ranks():
    """
    Reads the 'stats_to_date' table from projections.db, calculates percentile-based
    category ranks for existing stats, and saves the updated table.
    """
    print("\n--- Calculating and Adding Category Ranks to 'stats_to_date' ---")

    conn = None
    try:
        # 1. Connect to the database and read the table
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)

        # Check if table exists before reading
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stats_to_date'")
        if cursor.fetchone() is None:
            print(f"  Error: 'stats_to_date' table does not exist in {PROJECTIONS_DB_FILE}. Aborting ranks.")
            return

        df = pd.read_sql_query("SELECT * FROM stats_to_date", conn)

        if df.empty:
            print("  'stats_to_date' table is empty. Nothing to rank.")
            return

        print(f"  Loaded {len(df)} players from 'stats_to_date'.")

        # 2. Define the stats we *want* to rank (if they exist)
        skater_stats_to_rank = [
            'G', 'A', 'P', 'PPG', 'PPA', 'PPP', 'SHG', 'SHA', 'SHP',
            'HIT', 'BLK', 'PIM', 'FOW', 'SOG', 'plus_minus'
        ]

        # Note: 'SVpct' from your example is 'SV_PCT' in your create_stats_to_date_table function
        goalie_stats_to_rank = {
            'GS': False, 'W': False, 'L': True, 'GA': True, 'SA': False,
            'SV': False, 'SVpct': False, 'GAA': True, 'SHO': False, 'QS': False
        }

        # Get the set of columns that *actually* exist in the DataFrame
        existing_columns = set(df.columns)
        new_rank_columns = []

        # --- 3. Skater Ranking ---

        # Create a view of just the skaters
        # na=False ensures we don't accidentally drop players with no 'positions' data
        skater_mask = ~df['positions'].str.contains('G', na=False)
        if skater_mask.any():
            num_skaters = skater_mask.sum()
            print(f"  Ranking {num_skaters} skaters...")

            for stat in skater_stats_to_rank:
                if stat in existing_columns:
                    new_col_name = f"{stat}_cat_rank"
                    new_rank_columns.append(new_col_name)

                    # Ensure stat is numeric, fill NaNs with 0
                    df[stat] = pd.to_numeric(df[stat], errors='coerce').fillna(0)

                    # Get the ranks (1 to N) just for skaters, sorted descending
                    # .rank(method='first') handles ties, 'ascending=False' ranks highest value as 1
                    skater_ranks = df.loc[skater_mask, stat].rank(method='first', ascending=False)

                    # Calculate percentile based on rank
                    percentiles = skater_ranks / num_skaters

                    # Define ranking bins based on your logic
                    conditions = [
                        percentiles <= 0.05, percentiles <= 0.10, percentiles <= 0.15,
                        percentiles <= 0.20, percentiles <= 0.25, percentiles <= 0.30,
                        percentiles <= 0.35, percentiles <= 0.40, percentiles <= 0.45,
                        percentiles <= 0.50, percentiles <= 0.75
                    ]
                    choices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15]

                    # Apply ranks, default to 20. Use np.select on the percentile series
                    rank_points = np.select(conditions, choices, default=20)

                    # Add the new column, but only for skaters
                    df.loc[skater_mask, new_col_name] = rank_points
                    print(f"    Calculated ranks for skater stat: {stat}")
                else:
                    print(f"    Skipping skater stat (not found): {stat}")

        # --- 4. Goalie Ranking ---

        # Create a view of just the goalies
        goalie_mask = df['positions'].str.contains('G', na=False)
        if goalie_mask.any():
            num_goalies = goalie_mask.sum()
            print(f"  Ranking {num_goalies} goalies...")

            for stat, is_inverse in goalie_stats_to_rank.items():
                if stat in existing_columns:
                    new_col_name = f"{stat}_cat_rank"
                    new_rank_columns.append(new_col_name)

                    # Ensure stat is numeric, fill NaNs with 0
                    df[stat] = pd.to_numeric(df[stat], errors='coerce').fillna(0)

                    # Rank goalies, respecting inverse (e.g., GAA, L)
                    # 'ascending=is_inverse' means it's True for inverse stats (lower is better)
                    goalie_ranks = df.loc[goalie_mask, stat].rank(method='first', ascending=is_inverse)

                    percentiles = goalie_ranks / num_goalies

                    # Same ranking logic
                    conditions = [
                        percentiles <= 0.05, percentiles <= 0.10, percentiles <= 0.15,
                        percentiles <= 0.20, percentiles <= 0.25, percentiles <= 0.30,
                        percentiles <= 0.35, percentiles <= 0.40, percentiles <= 0.45,
                        percentiles <= 0.50, percentiles <= 0.75
                    ]
                    choices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15]

                    rank_points = np.select(conditions, choices, default=20)

                    # Add the new column, but only for goalies
                    df.loc[goalie_mask, new_col_name] = rank_points
                    print(f"    Calculated ranks for goalie stat: {stat}")
                else:
                    print(f"    Skipping goalie stat (not found): {stat}")

        # --- 5. Save back to Database ---

        # Fill any ranks that are still NaN (e.g., for skaters in goalie-rank columns) with 0 or a default
        # Or just leave them as NaN, which to_sql handles. Let's fill with 0 for tidiness.
        rank_cols_to_fill = [col for col in df.columns if col.endswith('_cat_rank')]
        df[rank_cols_to_fill] = df[rank_cols_to_fill].fillna(0).astype(int)

        print(f"  Saving {len(new_rank_columns)} new/updated rank columns back to 'stats_to_date'...")
        df.to_sql(
            'stats_to_date',
            conn,
            if_exists='replace',
            index=False,
            # Ensure key types are maintained
            dtype={'nhlplayerid': 'INTEGER', 'player_id': 'INTEGER'}
        )

        conn.commit()
        print("  Successfully saved ranks to 'stats_to_date'.")

    except sqlite3.Error as e:
        print(f"Database error during rank calculation: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An error occurred during rank calculation: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()


def create_combined_projections():
    """
    Creates a new table 'combined_projections' by merging 'projections'
    and 'stats_to_date'.

    - Identity columns are carried over (prioritizing 'stats_to_date').
    - Data columns existing in both tables are averaged.
    - Data columns existing in only one table are carried over.
    """
    print(f"\n--- Creating 'combined_projections' table in {PROJECTIONS_DB_FILE} ---")
    conn = None
    try:
        conn = sqlite3.connect(PROJECTIONS_DB_FILE)
        cursor = conn.cursor()

        # 1. Check if source tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projections'")
        if cursor.fetchone() is None:
            print(f"  Error: 'projections' table does not exist. Aborting.")
            return

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stats_to_date'")
        if cursor.fetchone() is None:
            print(f"  Error: 'stats_to_date' table does not exist. Aborting.")
            return

        # 2. Load tables into DataFrames
        print("  Reading 'projections' and 'stats_to_date' tables...")
        df_proj = pd.read_sql_query("SELECT * FROM projections", conn)
        df_stats = pd.read_sql_query("SELECT * FROM stats_to_date", conn)

        # --- NEW FIX: Standardize conflicting column names ---
        # This handles the 'gp' (proj) vs 'GP' (stats) conflict
        if 'gp' in df_proj.columns:
            print("  Standardizing 'gp' column to 'GP'...")
            df_proj = df_proj.rename(columns={'gp': 'GP'})
        # --- END FIX ---

        if df_proj.empty:
            print("  Warning: 'projections' table is empty.")
            return
        if df_stats.empty:
            print("  Warning: 'stats_to_date' table is empty.")
            return

        # 3. Perform the 'outer' merge
        df_merged = pd.merge(df_proj, df_stats, on='nhlplayerid', how='outer', suffixes=('_proj', '_stats'))

        # This will be our new, final DataFrame
        df_combined = pd.DataFrame()
        # Start by adding the primary key, handling NaNs from the outer join
        df_combined['nhlplayerid'] = df_merged['nhlplayerid'].dropna().astype(int)

        # 4. Define the identity columns (your list)
        identity_cols = [
            'player_name_normalized', 'player_name', 'team', 'age', 'player_id',
            'positions', 'status', 'lg_ppTimeOnIce', 'lg_ppTimeOnIcePctPerGame',
            'lg_ppAssists', 'lg_ppGoals', 'avg_ppTimeOnIce', 'avg_ppTimeOnIcePctPerGame',
            'total_ppAssists', 'total_ppGoals', 'player_games_played', 'team_games_played'
        ]

        print("  Processing identity columns...")
        for col in identity_cols:
            col_proj_suffixed = f"{col}_proj"
            col_stats_suffixed = f"{col}_stats"

            # Case 1: Overlap, has suffixes. Prioritize stats, fill with proj.
            if col_stats_suffixed in df_merged.columns and col_proj_suffixed in df_merged.columns:
                df_combined[col] = df_merged[col_stats_suffixed].fillna(df_merged[col_proj_suffixed])

            # Case 2: No overlap, original name. Check which table it came from.
            elif col in df_merged.columns:
                df_combined[col] = df_merged[col] # Just carry it over

            # Case 3: Exists only in one side (suffixed but no counterpart)
            elif col_stats_suffixed in df_merged.columns:
                 df_combined[col] = df_merged[col_stats_suffixed]
            elif col_proj_suffixed in df_merged.columns:
                 df_combined[col] = df_merged[col_proj_suffixed]


        # 5. Define the data columns (everything else)
        identity_cols_with_key = set(identity_cols + ['nhlplayerid'])
        proj_data_cols = set(df_proj.columns) - identity_cols_with_key
        stats_data_cols = set(df_stats.columns) - identity_cols_with_key
        all_data_cols = proj_data_cols.union(stats_data_cols) # Union of all *original* data col names

        print(f"  Processing {len(all_data_cols)} data columns (averaging/carrying over)...")

        for col in all_data_cols:
            col_proj_suffixed = f"{col}_proj"
            col_stats_suffixed = f"{col}_stats"

            # Case 1: Column overlaps, has suffixes -> Average them
            if col_proj_suffixed in df_merged.columns and col_stats_suffixed in df_merged.columns:
                series_proj = pd.to_numeric(df_merged[col_proj_suffixed], errors='coerce').fillna(0)
                series_stats = pd.to_numeric(df_merged[col_stats_suffixed], errors='coerce').fillna(0)
                df_combined[col] = (series_proj + series_stats) / 2

            # Case 2: Column is unique, no suffix -> Carry it over
            elif col in df_merged.columns:
                # Check if it was a proj-only column
                if col in proj_data_cols:
                    series_proj = pd.to_numeric(df_merged[col], errors='coerce').fillna(0)
                    df_combined[col] = series_proj
                # Check if it was a stats-only column
                elif col in stats_data_cols:
                    series_stats = pd.to_numeric(df_merged[col], errors='coerce').fillna(0)
                    df_combined[col] = series_stats

        # 6. Save the new table
        print(f"  Saving {len(df_combined)} records to 'combined_projections' table...")

        # Ensure key integer types are correct
        dtype_map = {}
        if 'nhlplayerid' in df_combined.columns:
            dtype_map['nhlplayerid'] = 'INTEGER'
        if 'player_id' in df_combined.columns:
            df_combined['player_id'] = pd.to_numeric(df_combined['player_id'], errors='coerce').fillna(pd.NA).astype('Int64')
            dtype_map['player_id'] = 'INTEGER'

        df_combined.to_sql(
            'combined_projections',
            conn,
            if_exists='replace',
            index=False,
            dtype=dtype_map
        )

        conn.commit()
        print("  Successfully created 'combined_projections' table.")

    except sqlite3.Error as e:
        print(f"Database error during 'combined_projections' creation: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An error occurred during 'combined_projections' creation: {e}", file=sys.stderr)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    setup_database() # Creates special_teams.db if needed
    fetch_team_standings() # Fetch and update team standings
    fetch_team_stats_summary()
    fetch_team_stats_weekly()

    # --- NEW FUNCTION CALL ADDED ---
    fetch_and_update_scoring_to_date()
    fetch_and_update_bangers_stats()
    fetch_and_update_goalie_stats()
    # Run the main data fetch and processing
    new_data_fetched = fetch_daily_pp_stats()

    # Only run the table creation and join if new data was actually fetched
    # or if we are just running it to refresh the tables
    # Let's always run them to ensure the tables are fresh

    print("\n--- Starting Post-Fetch Table Processing ---")

    # Create/update the "last game" summary table
    create_last_game_pp_table(DB_FILE)

    # Create/update the "last week" summary table
    create_last_week_pp_table(DB_FILE)

    # Join the new summary data into projections.db
    join_special_teams_data()
    copy_standings_to_projections()
    copy_team_stats_to_projections()
    copy_team_stats_weekly_to_projections()
    create_stats_to_date_table()
    calculate_and_save_to_date_ranks()
    create_combined_projections()
    print("\n--- Daily TOI Script Finished ---")
