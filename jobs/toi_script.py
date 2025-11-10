import requests
import pandas as pd
from datetime import date, timedelta
import time
import sqlite3
import os
import sys


MOUNT_PATH = "/var/data/dbs"

DB_FILE = os.path.join(MOUNT_PATH, "special_teams.db")
PROJECTIONS_DB_FILE = os.path.join(MOUNT_PATH, "projections.db")

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


if __name__ == "__main__":
    setup_database() # Creates special_teams.db if needed

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

    print("\n--- Daily TOI Script Finished ---")
