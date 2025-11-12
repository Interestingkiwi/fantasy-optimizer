"""
This script fetches all players from a Yahoo Fantasy league and stores them
in a local SQLite database.

It creates the necessary 'players' and 'metadata' tables and is
self-contained, handling its own API authentication and database connection.
"""

import argparse
import logging
import os
import sys
import sqlite3
import unicodedata
import re
import json
import shutil
from dotenv import load_dotenv
from datetime import date
from yfpy.query import YahooFantasySportsQuery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


MOUNT_PATH = "/var/data/dbs"

# --- Database Schema ---

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key_ TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    player_id TEXT NOT NULL UNIQUE,
    player_name TEXT NOT NULL,
    player_team TEXT,
    positions TEXT,
    status TEXT,
    player_name_normalized TEXT NOT NULL
);
"""

# --- Database Connection ---

def get_db_connection(league_id):
    """Gets a connection to the SQLite database."""
    # Point to the persistent disk path
    db_path = os.path.join(MOUNT_PATH, f"yahoo_player_ids.db")
    logger.info(f"Connecting to database at: {db_path}")

    # Check if the directory exists, if not, create it
    os.makedirs(MOUNT_PATH, exist_ok=True)

    return sqlite3.connect(db_path)

# --- API Authentication ---

def initialize_yahoo_query(league_id, consumer_key, consumer_secret):
    """
    Initializes the YahooFantasySportsQuery object, handling game_id lookup
    and using a persistent token file on the Render disk.
    """
    logger.debug("Initializing Yahoo query")

    # --- NEW: Bootstrap token from Render Secret File ---
    SECRET_TOKEN_PATH = "/etc/secrets/token.json"
    PERSISTENT_TOKEN_PATH = os.path.join(MOUNT_PATH, "token.json")

    try:
        # Ensure the persistent disk directory exists
        os.makedirs(MOUNT_PATH, exist_ok=True)

        # If the token doesn't exist on the persistent disk...
        if not os.path.exists(PERSISTENT_TOKEN_PATH):
            logger.info(f"Persistent token not found at {PERSISTENT_TOKEN_PATH}.")
            # ...check if the Secret File *does* exist.
            if os.path.exists(SECRET_TOKEN_PATH):
                logger.info(f"Secret File token found at {SECRET_TOKEN_PATH}. Copying to persistent disk...")
                # Copy it to the persistent disk for this and all future runs.
                shutil.copy2(SECRET_TOKEN_PATH, PERSISTENT_TOKEN_PATH)
                logger.info(f"Successfully copied secret token to {PERSISTENT_TOKEN_PATH}.")
            else:
                # This will happen if you run locally without the secret file
                logger.warning(f"No persistent token OR secret file token found. Proceeding with new auth.")
        else:
            logger.info(f"Persistent token found at {PERSISTENT_TOKEN_PATH}. No copy needed.")
    except Exception as e:
        logger.error(f"Error during token bootstrap logic: {e}")
    # --- END NEW LOGIC ---


    # --- RENDER-SPECIFIC LOGIC ---
    original_cwd = os.getcwd()
    try:
        # Change the current working directory to the persistent disk
        # This makes all file operations (like 'token.json') relative to this path.
        os.chdir(MOUNT_PATH)
        logger.info(f"Changed directory to persistent disk: {MOUNT_PATH}")
    except Exception as e:
        logger.critical(f"Failed to change directory to {MOUNT_PATH}: {e}")
        return None
    # --- END RENDER-SPECIFIC LOGIC ---

    # Define the token file path (now relative to the new CWD, i.e., /var/data/dbs/token.json)
    token_file_path = "token.json"
    logger.info(f"Checking for token at: {os.path.join(MOUNT_PATH, token_file_path)}")

    kwargs = {}

    # We *always* pass the consumer key and secret.
    if consumer_key and consumer_secret:
        kwargs["yahoo_consumer_key"] = consumer_key
        kwargs["yahoo_consumer_secret"] = consumer_secret
    else:
        logger.error("CRITICAL: Consumer key/secret are always required.")
        os.chdir(original_cwd) # Change back before exiting
        return None

    # Now, check if we HAVE a token file to use
    if os.path.exists(token_file_path):
        logger.info("Existing token.json found. Reading it and passing as yahoo_access_token_json.")
        try:
            with open(token_file_path, 'r') as f:
                token_data = json.load(f)
            kwargs["yahoo_access_token_json"] = token_data

        except Exception as e:
            logger.warning(f"Could not read token.json. Will start new auth. Error: {e}")
            # If reading fails, we just proceed, which triggers the verifier step.

    else:
        logger.info("token.json not found. Will start new auth flow.")
        # This will now only happen if the Secret File was *also* not found
        # and the script will (correctly) fail in the Render shell.

    try:
        yq = YahooFantasySportsQuery(
            league_id=league_id, game_code="nhl", **kwargs
        )

        game_info = yq.get_current_game_info()
        game_id = game_info.game_id
        logger.info(f"Successfully retrieved game_id: {game_id}")

        yq.game_id = game_id

        # --- MANUALLY SAVE THE TOKEN (EVERY TIME) ---
        # After a successful call, save the most up-to-date token
        # back to the persistent disk.
        if yq._yahoo_access_token_dict:
            logger.info("Auth/refresh successful. Saving/updating token.json...")
            try:
                with open(token_file_path, 'w') as f:
                    json.dump(yq._yahoo_access_token_dict, f)
                logger.info(f"Successfully saved token to {os.path.join(MOUNT_PATH, token_file_path)}")
            except Exception as e:
                logger.error(f"Failed to save token.json: {e}")
        else:
            logger.warning("Auth flow finished, but no token data was found in the object.")

        # --- Change back to the original directory ---
        os.chdir(original_cwd)
        logger.debug(f"Changed directory back to {original_cwd}")

        return yq

    except Exception as e:
        logger.critical(f"Failed to initialize Yahoo API query: {e}", exc_info=True)
        os.chdir(original_cwd) # Change back on error
        return None

# --- Data Fetching ---

def fetch_and_store_players(con, yq):
    """
    Writes player name, normalized player name, team, and yahoo id to players
    table for all players in the league.
    """
    logger.info("Fetching player info...")

    try:
        players = yq.get_league_players()
    except Exception as e:
        logger.error(f"Failed to fetch league players from API: {e}", exc_info=True)
        return

    TEAM_TRICODE_MAP = {
        "TB": "TBL",
        "NJ": "NJD",
        "SJ": "SJS",
        "LA": "LAK",
        "MON": "MTL",
        "WAS": "WSH"
    }

    player_data_to_insert = []
    for player in players:
        try:
            # --- THIS IS THE FIX ---
            # Cast the player_id to a string so the comparison works
            player_id = str(player.player_id)

            player_name = player.name.full
            positions = player.display_position
            status = player.status

            # Normalize player name
            nfkd_form = unicodedata.normalize('NFKD', player_name.lower())
            ascii_name = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
            player_name_normalized = re.sub(r'[^a-z0-9]', '', ascii_name)

            # Now this comparison will work (string vs string)
            if player_id == "6777":  # Sebastian Aho
                player_name_normalized += "f"
                logger.info(f"Appended 'f' to normalized name for player_id {player_id}")
            elif player_id == "7520":  # Elias Pettersson
                player_name_normalized += "f"
                logger.info(f"Appended 'f' to normalized name for player_id {player_id}")

            player_team_abbr = player.editorial_team_abbr.upper()
            player_team = TEAM_TRICODE_MAP.get(player_team_abbr, player_team_abbr)

            player_data_to_insert.append((
                player_id,
                player_name,
                player_team,
                positions,
                status,
                player_name_normalized
            ))
        except Exception as e:
            logger.warning(f"Failed to process player: {player}. Error: {e}")

    if not player_data_to_insert:
        logger.warning("No player data was processed. Nothing to insert.")
        return

    try:
        # Using REPLACE is still good practice for future runs
        sql = """
            INSERT OR REPLACE INTO players (
                player_id,
                player_name,
                player_team,
                positions,
                status,
                player_name_normalized
            ) VALUES (?, ?, ?, ?, ?, ?)
        """
        con.executemany(sql, player_data_to_insert)
        con.commit()
        logger.info(f"Successfully inserted or replaced data for {len(player_data_to_insert)} players.")

        # Update metadata
        today = date.today().isoformat()
        sql_meta = "INSERT OR REPLACE INTO metadata (key_, value) VALUES (?, ?)"
        con.execute(sql_meta, ('last_player_fetch', today))
        con.commit()
        logger.info(f"Updated 'last_player_fetch' metadata to {today}.")

    except Exception as e:
        logger.error(f"Failed to insert player data into database: {e}", exc_info=True)
        con.rollback()
# --- Main Execution ---

def run():
    """Main function to run the player fetcher."""
    load_dotenv()  # <-- ADD THIS LINE

    parser = argparse.ArgumentParser(
        description="Fetch Yahoo Fantasy Hockey players and store them in SQLite."
    )
    parser.add_argument("league_id", type=int, help="Your Yahoo fantasy league ID.")
    parser.add_argument("-k", "--yahoo-consumer-key", help="Yahoo consumer key.")
    parser.add_argument("-s", "--yahoo-consumer-secret", help="Yahoo consumer secret.")
    args = parser.parse_args()

    con = None
    try:
        # 1. Connect to and set up the database
        con = get_db_connection(args.league_id)
        con.executescript(SCHEMA_SQL)
        con.commit()
        logger.info("Database schema checked and applied.")

        # 2. Connect to the Yahoo API
        logger.info("Connecting to Yahoo Fantasy API...")
        yq = initialize_yahoo_query(
            args.league_id,
            args.yahoo_consumer_key,
            args.yahoo_consumer_secret
        )

        if yq is None:
            raise Exception("Yahoo API initialization failed. Exiting.")

        logger.info("Successfully connected to Yahoo API.")

        # 3. Fetch and store player data
        fetch_and_store_players(con, yq)

        logger.info("Player fetch complete.")

    except Exception as e:
        logger.critical(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if con:
            con.close()
            logger.info("Database connection closed.")

if __name__ == "__main__":
    run()
