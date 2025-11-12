"""
Processes and joins data in the fantasy hockey database.

This script reads two sets of projection files (Proj1 and Proj2), each
consisting of a separate skater file and goalie file.
It processes each set, calculates ranks, and saves them to 'proj1' and 'proj2' tables.
It then combines 'proj1' and 'proj2' into a final 'projections' table.
It then joins the 'projections' table with Yahoo player ID data and
creates a 'missing_id' table for any players who did not match.

It also fetches the NHL schedule and creates schedule-related tables.

Author: Jason Druckenmiller
Date: 10/31/2025
"""

import pandas as pd
import sqlite3
import sys
import os
import re
import csv
import json
import requests
import time
import unicodedata
from datetime import date, timedelta
from collections import defaultdict, Counter

# --- Constants ---
MOUNT_PATH = "/var/data/dbs" # Define the persistent storage path
SEED_DATA_DIR = "seed_data"   # Define the path to your seed data

# --- Source Projection Files (Read-Only) ---
PROJ1_SKATER_FILE = os.path.join(SEED_DATA_DIR, 'proj1s.csv')
PROJ1_GOALIE_FILE = os.path.join(SEED_DATA_DIR, 'proj1g.csv')
PROJ2_SKATER_FILE = os.path.join(SEED_DATA_DIR, 'proj2s.csv')
PROJ2_GOALIE_FILE = os.path.join(SEED_DATA_DIR, 'proj2g.csv')

# --- Writable Database Files (on Persistent Disk) ---
DB_FILE = os.path.join(MOUNT_PATH, 'projections.db')
YAHOO_DB_FILE = os.path.join(MOUNT_PATH, 'yahoo_player_ids.db')
YAHOO_TABLE_NAME = 'players'

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
    "T.B": "TBL",
    "N.J": "NJD",
    "S.J": "SJS",
    "L.A": "LAK",
    "MON": "MTL",
    "WAS": "WSH"
}


# --- Function Definitions ---

def setup_database_connection(db_file):
    """
    Sets up the connection to the SQLite database.
    Returns the connection object.
    """
    print(f"Setting up database connection to {db_file}...")
    try:
        conn = sqlite3.connect(db_file)
        print("Database connection successful.")
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database {db_file}: {e}", file=sys.stderr)
        return None


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
        'goals': 'G',
        'g':'G',
        'assists': 'A',
        'a':'A',
        'points': 'P',
        'p':'P',
        'pp_points': 'PPP',
        'ppp':'PPP',
        'hits': 'HIT',
        'hit':'HIT',
        'sog': 'SOG',
        'blk': 'BLK',
        'w': 'W',
        'so': 'SHO',
        'sho':'SHO',
        'sv%': 'SVpct',
        'svpct': 'SVpct', # Added for consistency
        'ga': 'GA',
        'plus_minus': 'plus_minus',
        'shg': 'SHG',
        'sha': 'SHA',
        'shp': 'SHP',
        'pim': 'PIM',
        'fow': 'FOW',
        'fol': 'FOL',
        'ppg': 'PPG',
        'ppa': 'PPA',
        'gaa': 'GAA',
        'gs': 'GS',
        'sv': 'SV',
        'sa': 'SA',
        'qs': 'QS',
        'l':'L'
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


def calculate_and_add_category_ranks(player_data):
    """
    Calculates category ranks for specified stats based on percentile and adds them to player data.

    Args:
        player_data (dict): Dictionary of player data, keyed by player_name_normalized.

    Returns:
        tuple: A tuple containing:
            - dict: The updated player_data dictionary
            - list: A list of the new column names created for the ranks
    """
    new_rank_columns = []

    # --- Skater Ranking ---
    skater_stats_to_rank = [
        'G', 'A', 'P', 'PPG', 'PPA', 'PPP', 'SHG', 'SHA', 'SHP',
        'HIT', 'BLK', 'PIM', 'FOW', 'SOG', 'plus_minus'
    ]
    skaters = {name: data for name, data in player_data.items() if 'G' not in data.get('positions', '')}
    num_skaters = len(skaters)

    if num_skaters > 0:
        for stat in skater_stats_to_rank:
            new_col_name = f"{stat}_cat_rank"
            new_rank_columns.append(new_col_name)

            stat_values = []
            for name, data in skaters.items():
                try:
                    value = float(data.get(stat, 0.0))
                except (ValueError, TypeError):
                    value = 0.0
                stat_values.append((name, value))

            stat_values.sort(key=lambda x: x[1], reverse=True)

            for i, (name, value) in enumerate(stat_values):
                percentile = (i + 1) / num_skaters
                rank_points = 0
                if percentile <= 0.05: rank_points = 1
                elif percentile <= 0.10: rank_points = 2
                elif percentile <= 0.15: rank_points = 3
                elif percentile <= 0.20: rank_points = 4
                elif percentile <= 0.25: rank_points = 5
                elif percentile <= 0.30: rank_points = 6
                elif percentile <= 0.35: rank_points = 7
                elif percentile <= 0.40: rank_points = 8
                elif percentile <= 0.45: rank_points = 9
                elif percentile <= 0.50: rank_points = 10
                elif percentile <= 0.75: rank_points = 15
                else: rank_points = 20
                player_data[name][new_col_name] = rank_points

    # --- Goalie Ranking ---
    goalie_stats_to_rank = {
        'GS': False, 'W': False, 'L': True, 'GA': True, 'SA': False,
        'SV': False, 'SVpct': False, 'GAA': True, 'SHO': False, 'QS': False
    }
    goalies = {name: data for name, data in player_data.items() if 'G' in data.get('positions', '')}
    num_goalies = len(goalies)

    if num_goalies > 0:
        for stat, is_inverse in goalie_stats_to_rank.items():
            new_col_name = f"{stat}_cat_rank"
            new_rank_columns.append(new_col_name)

            stat_values = []
            for name, data in goalies.items():
                try:
                    value = float(data.get(stat, 0.0))
                except (ValueError, TypeError):
                    value = 0.0
                stat_values.append((name, value))

            stat_values.sort(key=lambda x: x[1], reverse=not is_inverse)

            for i, (name, value) in enumerate(stat_values):
                percentile = (i + 1) / num_goalies
                rank_points = 0
                if percentile <= 0.05: rank_points = 1
                elif percentile <= 0.10: rank_points = 2
                elif percentile <= 0.15: rank_points = 3
                elif percentile <= 0.20: rank_points = 4
                elif percentile <= 0.25: rank_points = 5
                elif percentile <= 0.30: rank_points = 6
                elif percentile <= 0.35: rank_points = 7
                elif percentile <= 0.40: rank_points = 8
                elif percentile <= 0.45: rank_points = 9
                elif percentile <= 0.50: rank_points = 10
                elif percentile <= 0.75: rank_points = 15
                else: rank_points = 20
                player_data[name][new_col_name] = rank_points

    return player_data, new_rank_columns


def process_separate_files_to_table(cursor, skater_csv_file, goalie_csv_file, target_table_name):
    """
    Reads a SEPARATE skater and goalie CSV, combines them in memory,
    calculates ranks, and saves to a single table.
    """
    print(f"\n--- Setting up Table from SEPARATE Files: '{target_table_name}' ---")
    try:
        # Part 1: Process all player data into memory first
        player_data = {}
        skater_headers_sanitized = []
        goalie_headers_sanitized = []

        # Process Skater File
        print(f"Processing Skater File: {skater_csv_file}")
        with open(skater_csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header_raw = next(reader)
            header_lower = [h.strip().lower() for h in header_raw]
            skater_headers_sanitized = sanitize_header(header_raw)

            try:
                p_name_idx = header_lower.index('player name')
                gp_idx = header_lower.index('gp')
                pos_idx = header_lower.index('positions')
            except ValueError as e:
                raise ValueError(f"Missing column in {skater_csv_file}: {e}")

            skater_stats_to_exclude = ['player name', 'age', 'positions', 'team', 'salary', 'gp org', 'gp', 'toi org es', 'toi org pp', 'toi org pk', 'toi es', 'toi pp', 'toi pk', 'total toi', 'rank', 'playerid', 'fantasy team']
            skater_stat_indices = [i for i, h in enumerate(header_lower) if h not in skater_stats_to_exclude and h.strip() != '']

            for row in reader:
                # Skip goalies if any are in this file
                if not row or (pos_idx < len(row) and 'G' in row[pos_idx]):
                    continue
                calculate_per_game_stats(row, gp_idx, skater_stat_indices)
                player_name = row[p_name_idx]
                if not player_name: continue
                player_name_normalized = normalize_name(player_name)

                data_dict = {skater_headers_sanitized[i]: val for i, val in enumerate(row)}

                # --- TEAM FIX ---
                team_abbr = data_dict.get('team', '').upper() # Get uppercase version
                if team_abbr in TEAM_TRICODE_MAP:
                    data_dict['team'] = TEAM_TRICODE_MAP[team_abbr] # Fix "TB" -> "TBL"
                else:
                    data_dict['team'] = team_abbr # Standardize "ana" -> "ANA"
                # --- END FIX ---

                player_data[player_name_normalized] = data_dict
                player_data[player_name_normalized]['player_name_normalized'] = player_name_normalized

        # Process Goalie File
        print(f"Processing Goalie File: {goalie_csv_file}")
        with open(goalie_csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header_raw = next(reader)
            header_lower = [h.strip().lower() for h in header_raw]
            goalie_headers_sanitized = sanitize_header(header_raw)

            try:
                p_name_idx = header_lower.index('player name')
                gp_goalie_idx = header_lower.index('gs')
            except ValueError as e:
                raise ValueError(f"Missing column in {goalie_csv_file}: {e}")

            # --- FIX: Removed 'ga' so it gets processed as a per-game stat ---
            goalie_stats_to_exclude = ['player name', 'team', 'age', 'position', 'salary', 'gs', 'sv%', 'gaa', 'rank', 'playerid', 'fantasy team']
            # --- END FIX ---

            goalie_stat_indices = [i for i, h in enumerate(header_lower) if h not in goalie_stats_to_exclude and h.strip() != '']

            for row in reader:
                if not row: continue
                # This will now process GA / GS just like W / GS
                calculate_per_game_stats(row, gp_goalie_idx, goalie_stat_indices)

                player_name = row[p_name_idx]
                if not player_name: continue
                player_name_normalized = normalize_name(player_name)

                goalie_row_data = {goalie_headers_sanitized[i]: val for i, val in enumerate(row)}

                # --- TEAM FIX ---
                team_abbr = goalie_row_data.get('team', '').upper() # Get uppercase version
                if team_abbr in TEAM_TRICODE_MAP:
                    goalie_row_data['team'] = TEAM_TRICODE_MAP[team_abbr] # Fix "TB" -> "TBL"
                else:
                    goalie_row_data['team'] = team_abbr # Standardize "ana" -> "ANA"
                # --- END FIX ---

                if 'positions' not in goalie_row_data or not goalie_row_data['positions']:
                    goalie_row_data['positions'] = 'G'

                if player_name_normalized in player_data:
                    player_data[player_name_normalized].update(goalie_row_data)
                else:
                    goalie_row_data['player_name_normalized'] = player_name_normalized
                    player_data[player_name_normalized] = goalie_row_data

        print(f"Processed data for {len(player_data)} unique players from both files.")

        # Part 2: Calculate and add category ranks to the in-memory data
        print("Calculating category ranks...")
        player_data, new_rank_columns = calculate_and_add_category_ranks(player_data)
        print(f"Added {len(new_rank_columns)} category rank columns.")

        # Part 3: Define schema from all headers (original + new) and create the table
        all_headers = list(dict.fromkeys(skater_headers_sanitized + goalie_headers_sanitized))
        final_headers = [h for h in all_headers if h] # Remove any empty headers
        final_headers.extend(new_rank_columns)  # Add new rank columns to the final list of headers

        if 'player_name' not in final_headers: raise ValueError("'player_name' column not found.")

        columns_def_parts = [f'"{c}" REAL' for c in final_headers if c not in ['player_name', 'positions']]
        columns_def_parts.insert(0, 'player_name TEXT PRIMARY KEY')
        columns_def_parts.insert(1, 'positions TEXT')
        columns_def_parts.append('player_name_normalized TEXT')

        create_table_sql = f'CREATE TABLE {target_table_name} ({", ".join(columns_def_parts)})'
        create_index_sql = f'CREATE INDEX idx_norm_name_{target_table_name} ON {target_table_name}(player_name_normalized)'

        cursor.execute(f"DROP TABLE IF EXISTS {target_table_name}")
        cursor.execute(create_table_sql)
        cursor.execute(create_index_sql)
        print(f"Table '{target_table_name}' and index created with a unified schema.")

        # Part 4: Insert the combined and augmented data into the database
        insert_headers = final_headers + ['player_name_normalized']
        placeholders = ", ".join(['?'] * len(insert_headers))
        insert_sql = f'INSERT OR REPLACE INTO {target_table_name} ({", ".join(f"`{h}`" for h in insert_headers)}) VALUES ({placeholders})'

        rows_to_insert = []
        for player_name_normalized, data_dict in player_data.items():
            ordered_row = tuple(data_dict.get(h, None) for h in insert_headers)
            rows_to_insert.append(ordered_row)

        cursor.executemany(insert_sql, rows_to_insert)
        print(f"Populated '{target_table_name}' table with {len(rows_to_insert)} rows.")

    except FileNotFoundError as e:
        print(f"ERROR: A required CSV file was not found: {e.filename}", file=sys.stderr)
        raise
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"An unexpected error occurred in process_separate_files_to_table: {e}", file=sys.stderr)
        raise


def create_averaged_projections(conn, cursor):
    """
    Combines 'proj1' and 'proj2' tables into a final 'projections' table.
    It averages shared stats and coalesces player info.
    """
    print("\n--- Creating Final Averaged Projections Table ---")
    try:
        # Load tables into pandas DataFrames
        df1 = pd.read_sql_query("SELECT * FROM proj1", conn)
        df2 = pd.read_sql_query("SELECT * FROM proj2", conn)
        print(f"Loaded {len(df1)} rows from proj1 and {len(df2)} rows from proj2.")

        # Merge on player_name_normalized using an outer join to keep all players
        merged_df = pd.merge(df1, df2, on='player_name_normalized', how='outer', suffixes=('_p1', '_p2'))
        print(f"Total unique players after merge: {len(merged_df)}")

        # Define columns for coalescing (info) vs. averaging (stats)
        # This will create a 'playerid' column in final_df, preferring p1's value
        COALESCE_COLS = ['player_name', 'positions', 'team', 'age', 'playerid', 'fantasy_team']

        # Get all unique column names from both tables
        cols_p1 = set(df1.columns)
        cols_p2 = set(df2.columns)

        # Define columns to ignore from averaging
        ignore_cols = set(COALESCE_COLS + ['player_name_normalized'])

        # Find all stat columns
        stat_cols_p1 = cols_p1 - ignore_cols
        stat_cols_p2 = cols_p2 - ignore_cols
        all_stat_cols = stat_cols_p1.union(stat_cols_p2)

        final_df = pd.DataFrame()
        final_df['player_name_normalized'] = merged_df['player_name_normalized']

        # 1. Handle COALESCE_COLS (Take p1 value, fill with p2 if p1 is null)
        print("Coalescing player information columns...")
        for col in COALESCE_COLS:
            # Check if columns exist (e.g., 'fantasy_team' might not be in all)
            col_p1_name = f'{col}_p1'
            col_p2_name = f'{col}_p2'
            if col_p1_name in merged_df:
                final_df[col] = merged_df[col_p1_name].fillna(merged_df.get(col_p2_name))
            elif col_p2_name in merged_df:
                final_df[col] = merged_df[col_p2_name]
            else:
                pass # Column doesn't exist in either table

        # --- NEW UPDATED CODE BLOCK START ---
        print("Adding and cleaning nhlplayerid from proj2 data...")
        proj2_id_data = None
        if 'playerid_p2' in merged_df:
            # Case 1: playerid was in BOTH proj1 and proj2. Use the suffixed p2 column.
            print("Found 'playerid_p2' column. Using it for nhlplayerid.")
            proj2_id_data = merged_df['playerid_p2']
        elif 'playerid' in merged_df.columns and 'playerid_p1' not in merged_df.columns:
            # Case 2: playerid was ONLY in proj2. Use the unsuffixed 'playerid' column.
            # (The 'playerid_p1' check confirms proj1 didn't have this column)
            print("Found unsuffixed 'playerid' column (from proj2). Using it for nhlplayerid.")
            proj2_id_data = merged_df['playerid']

        if proj2_id_data is not None:
            # We found the correct data source, now process it
            nhl_id_col = pd.to_numeric(proj2_id_data, errors='coerce')
            nhl_id_col = nhl_id_col.fillna(pd.NA)
            final_df['nhlplayerid'] = nhl_id_col.astype('Int64')
            print("Successfully created 'nhlplayerid' column.")
        else:
            # This handles cases where proj2 had no playerid, or it was in p1 only.
            print("Warning: Could not find a 'playerid' column from proj2 data. Creating empty 'nhlplayerid'.")
            final_df['nhlplayerid'] = pd.NA
            final_df['nhlplayerid'] = final_df['nhlplayerid'].astype('Int64')
        # --- NEW UPDATED CODE BLOCK END ---

        # 2. Handle STAT_COLS (Average, or carry over if unique)
        print(f"Averaging {len(all_stat_cols)} stat columns...")
        for col in all_stat_cols:
            col_p1_name = f'{col}_p1'
            col_p2_name = f'{col}_p2'

            in_p1 = col_p1_name in merged_df.columns
            in_p2 = col_p2_name in merged_df.columns

            if in_p1 and in_p2:
                # Stat is in BOTH tables: average them
                # .mean(axis=1) gracefully handles if one value is NaN (it just returns the other)
                col1 = pd.to_numeric(merged_df[col_p1_name], errors='coerce')
                col2 = pd.to_numeric(merged_df[col_p2_name], errors='coerce')
                final_df[col] = pd.concat([col1, col2], axis=1).mean(axis=1)
            elif in_p1:
                # Stat is ONLY in proj1: carry it over
                final_df[col] = pd.to_numeric(merged_df[col_p1_name], errors='coerce')
            elif in_p2:
                # Stat is ONLY in proj2: carry it over
                final_df[col] = pd.to_numeric(merged_df[col_p2_name], errors='coerce')

        # 3. Save the final averaged DataFrame to the 'projections' table
        print(f"Saving {len(final_df)} players to final 'projections' table...")

        # --- MODIFIED LINE: Added dtype parameter to force INTEGER type ---
        final_df.to_sql('projections',
                        conn,
                        if_exists='replace',
                        index=False,
                        dtype={'nhlplayerid': 'INTEGER'})
        # --- END MODIFICATION ---

        # Add an index on player_name_normalized for the new table
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_normalized_name_projections ON projections(player_name_normalized)')
        print("Final 'projections' table created successfully.")

        # 4. Clean up (commented out as requested)
        # print("\nCleaning up temporary tables...")
        # cursor.execute("DROP TABLE IF EXISTS proj1")
        # cursor.execute("DROP TABLE IF EXISTS proj2")
        # print("Temporary tables 'proj1' and 'proj2' dropped.")

    except Exception as e:
        print(f"An error occurred during averaging: {e}", file=sys.stderr)
        raise


def join_yahoo_ids(conn, cursor):
    """
    Joins the final 'projections' table with Yahoo player IDs and positions
    from an external DB. This will OVERWRITE the 'positions' column.

    It also creates a 'missing_id' table for any players who did not match.
    """
    print("\n--- Joining Yahoo Player ID Data ---")
    try:
        # 1. Load the newly created 'projections' table
        df_proj = pd.read_sql_query("SELECT * FROM projections", conn)

        # 2. Attach the Yahoo DB and load the required columns
        print(f"Attaching Yahoo DB: {YAHOO_DB_FILE}")
        cursor.execute(f"ATTACH DATABASE '{YAHOO_DB_FILE}' AS yahoo_db")

        # Use 'player_name_normalized' from Yahoo DB
        yahoo_query = f"SELECT player_name_normalized, player_id, positions,status FROM yahoo_db.{YAHOO_TABLE_NAME}"
        df_yahoo = pd.read_sql_query(yahoo_query, conn)
        print(f"Loaded {len(df_yahoo)} players from Yahoo DB.")

        # 3. Drop the original 'positions' column from projections
        if 'positions' in df_proj.columns:
            df_proj = df_proj.drop(columns=['positions'])

        # 4. Merge with the Yahoo data (left join)
        #   Join on 'player_name_normalized'
        df_final = pd.merge(df_proj, df_yahoo, on='player_name_normalized', how='left')

        # --- Create the missing_id table ---
        # Find rows where the merge failed (player_id from Yahoo is null)
        missing_mask = df_final['player_id'].isnull()
        df_missing = df_final[missing_mask][['player_name', 'player_name_normalized', 'team']]

        if not df_missing.empty:
            print(f"WARNING: {len(df_missing)} players did not match a Yahoo ID.")
            print(f"Saving these players to 'missing_id' table for review...")
            df_missing.to_sql('missing_id', conn, if_exists='replace', index=False)
        else:
            print("All players successfully matched with a Yahoo ID.")
            # Ensure the table is empty if it existed before
            cursor.execute("DROP TABLE IF EXISTS missing_id")
        # --- END NEW SECTION ---

        # 5. Save the final DataFrame back to the 'projections' table
        print(f"Saving {len(df_final)} players back to 'projections' table with Yahoo data...")
        # --- MODIFIED LINE: Added dtype parameter AGAIN to ensure it persists ---
        # This is redundant if join_yahoo_ids is called *after*
        # create_averaged_projections, but it's safer to have it here too
        # in case the column is re-inferred.

        # Let's check the logic. join_yahoo_ids *replaces* the table again.
        # The `df_final` here is created from `df_proj`, which was read *after*
        # create_averaged_projections. `df_proj` should have the 'nhlplayerid'
        # column. Let's ensure the type is correct *before* this final save.

        if 'nhlplayerid' in df_final.columns:
            # Re-apply the pandas Int64 type in case it was lost during the merge
            df_final['nhlplayerid'] = pd.to_numeric(df_final['nhlplayerid'], errors='coerce').fillna(pd.NA).astype('Int64')

        df_final.to_sql('projections',
                        conn,
                        if_exists='replace',
                        index=False,
                        dtype={'nhlplayerid': 'INTEGER', 'player_id': 'INTEGER'}) # Also fixing player_id from yahoo
        # --- END MODIFICATION ---

        # 6. Re-create the index
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_normalized_name_projections ON projections(player_name_normalized)')

        # 7. Detach the Yahoo DB
        cursor.execute("DETACH DATABASE yahoo_db")
        print("Successfully joined Yahoo data and detached DB.")

    except sqlite3.OperationalError as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        print(f"Please ensure '{YAHOO_DB_FILE}' exists and contains a table named '{YAHOO_TABLE_NAME}'.", file=sys.stderr)
        # Detach if attach was successful but query failed
        try:
            cursor.execute("DETACH DATABASE yahoo_db")
        except:
            pass
        raise
    except Exception as e:
        print(f"An error occurred during Yahoo join: {e}", file=sys.stderr)
        try:
            cursor.execute("DETACH DATABASE yahoo_db")
        except:
            pass
        raise


def get_full_nhl_schedule(start_date, end_date):
    """Fetches the entire season's NHL game schedule by iterating week by week."""
    all_games = {} # Use a dictionary to store unique games to avoid duplicates
    current_date = start_date

    print(f"Fetching full 2025-2026 season schedule for all teams (week by week)...")

    while current_date <= end_date:
        url = f"https://api-web.nhle.com/v1/schedule/{current_date.strftime('%Y-%m-%d')}"
        print(f"Fetching schedule for week of {current_date.strftime('%Y-%m-%d')}...")

        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            for week_data in data.get('gameWeek', []):
                game_date_str = week_data.get('date')
                for game in week_data.get('games', []):
                    home_team = game.get('homeTeam', {}).get('abbrev')
                    away_team = game.get('awayTeam', {}).get('abbrev')
                    # Create a unique key for each game to avoid duplicates
                    game_key = f"{game_date_str}-{home_team}-{away_team}"

                    if game_key not in all_games:
                        all_games[game_key] = {
                            'date': game_date_str,
                            'home_team': home_team,
                            'away_team': away_team
                        }

        except requests.exceptions.RequestException as e:
            print(f"\n❌ Error fetching schedule for week of {current_date.strftime('%Y-%m-%d')}: {e}")
            # Continue to the next week even if one week fails

        # Move to the next week
        current_date += timedelta(days=7)
        time.sleep(0.1) # Be polite to the API server

    game_list = list(all_games.values())
    print(f"\nSuccessfully fetched schedule data for {len(game_list)} unique games.")
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
    off_days = [(day,) for day, count in games_per_day.items() if count * 4 < NHL_TEAM_COUNT]
    cursor.executemany("INSERT INTO off_days VALUES (?)", sorted(off_days))
    print(f"Table 'off_days' created and populated with {len(off_days)} dates.")


# --- Main Execution ---

def run():
    """
    Main function to run the data pipeline.
    """
    print("--- Starting Projection Database Creation ---")
    conn = None
    try:
        # 1. Set up database connection
        conn = setup_database_connection(DB_FILE)
        if conn is None:
            raise Exception("Failed to create database connection.")

        cursor = conn.cursor()

        # 2. Process Proj1 (Separate files) into 'proj1' table
        process_separate_files_to_table(cursor, PROJ1_SKATER_FILE, PROJ1_GOALIE_FILE, 'proj1')

        # 3. Process Proj2 (Separate files) into 'proj2' table
        process_separate_files_to_table(cursor, PROJ2_SKATER_FILE, PROJ2_GOALIE_FILE, 'proj2')

        # 4. Create the final averaged 'projections' table from 'proj1' and 'proj2'
        create_averaged_projections(conn, cursor)

        # 5. Join the new 'projections' table with Yahoo data
        join_yahoo_ids(conn, cursor)

        # 6. Fetch the full NHL schedule
        games = get_full_nhl_schedule(START_DATE, END_DATE)

        # 7. Create all schedule-related tables
        setup_schedule_tables(cursor, games)

        # 8. Commit all changes to the database
        conn.commit()
        print("\nAll database operations committed successfully.")

    except Exception as e:
        print(f"\n--- An Error Occurred! ---", file=sys.stderr)
        print(f"Error: {e}", file=sys.stderr)
        print("Rolling back any uncommitted changes.", file=sys.stderr)
        if conn:
            conn.rollback()
    finally:
        # 9. Close connection
        if conn:
            conn.close()
            print("Database connection closed.")

    print("--- Projection Database Creation Finished ---")

if __name__ == "__main__":
    run()
