from flask import Blueprint, jsonify, session
import logging
from datetime import timezone

# We now import the 'requires_auth' decorator you will create in app.py
# We also need the GCS and storage clients that are defined in app.py
from app import (
    requires_auth,
    storage_client,  # Import the initialized GCS client
    gcs_bucket       # Import the GCS bucket object
)

# 1. Create the Blueprint
api = Blueprint('api_v1', __name__, url_prefix='/api/v1')


# 2. Define your routes
@api.route("/league/<league_id>/database-status")
@requires_auth # Use your existing auth decorator
def api_get_database_status(league_id):
    """
    Checks GCS for a league's database and returns its status.
    This is for the mobile app's main "database" screen.

    The @requires_auth decorator will automatically check if the user
    is logged in and if they have access to this league_id.
    """
    if not league_id:
        return jsonify({"error": "League ID is required."}), 400

    if not gcs_bucket:
        logging.error("api_v1: GCS_BUCKET_NAME not set or GCS client failed to init.")
        return jsonify({"error": "Server GCS is not configured."}), 500

    db_filename = None
    blob_to_check = None
    db_filename_prefix = f'yahoo-{league_id}-'
    remote_path_prefix = f'league-dbs/{db_filename_prefix}'

    try:
        logging.info(f"API checking GCS for: {remote_path_prefix}")

        # Find the first blob that matches the prefix
        for blob in gcs_bucket.list_blobs(prefix=remote_path_prefix):
            blob_to_check = blob
            db_filename = blob.name.split('/')[-1]
            break # We only care about the first (and likely only) one

        if not blob_to_check or not db_filename:
            logging.warning(f"API: No DB found for league {league_id}")
            # The database does not exist. Tell the app.
            return jsonify({
                "exists": False,
                "message": "No database found. Please build one on the website."
            }), 404

        # --- DB EXISTS ---
        # Get metadata
        last_updated_utc = blob_to_check.updated.isoformat()
        league_name_from_file = db_filename.replace(f'yahoo-{league_id}-', '').replace('.db', '')

        # Return the good status
        return jsonify({
            "exists": True,
            "league_id": league_id,
            "league_name": league_name_from_file,
            "filename": db_filename,
            "last_updated_utc": last_updated_utc,
            "size_bytes": blob_to_check.size
        })

    except Exception as e:
        logging.error(f"Error checking GCS status for league {league_id}: {e}", exc_info=True)
        return jsonify({"error": "An error occurred checking database status."}), 500
