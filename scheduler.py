import os
import sys
import subprocess
import logging
from apscheduler.schedulers.background import BackgroundScheduler # <-- CHANGED

# Set up basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def run_script(script_path, *args):
    """
    Helper function to run a python script as a subprocess.
    """
    logger.info(f"--- Starting script: {script_path} ---")
    try:
        # Use sys.executable to ensure we use the same python interpreter
        process = subprocess.run(
            [sys.executable, script_path, *args],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Output for {script_path}:\n{process.stdout}")
        if process.stderr:
            logger.warning(f"Stderr for {script_path}:\n{process.stderr}")
        logger.info(f"--- Finished script: {script_path} ---")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"--- FAILED script: {script_path} ---")
        logger.error(f"Return Code: {e.returncode}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        return False

def run_daily_job():
    """
    Runs the daily (Tue-Sun) job: just the toi_script.
    """
    logger.info("Starting daily (Tue-Sun) job: run_daily_job")
    run_script("jobs/toi_script.py")

def run_weekly_job():
    """
    Runs the full weekly (Monday) job sequence.
    """
    logger.info("Starting weekly (Monday) job: run_weekly_job")

    # Get required env vars for the subprocess
    league_id = os.environ.get('LEAGUE_ID')
    key = os.environ.get('YAHOO_CONSUMER_KEY')
    secret = os.environ.get('YAHOO_CONSUMER_SECRET')

    if not all([league_id, key, secret]):
        logger.error("Missing required environment variables (LEAGUE_ID, YAHOO_CONSUMER_KEY, YAHOO_CONSUMER_SECRET) for weekly job.")
        return

    # Run the scripts in sequence. If one fails, stop.
    if run_script("jobs/fetch_player_ids.py", league_id, "-k", key, "-s", secret):
        if run_script("jobs/create_projection_db.py"):
            run_script("jobs/toi_script.py")

def start_scheduler():
    """
    Initializes and starts the non-blocking scheduler.
    """
    logger.info("Initializing background scheduler...")
    scheduler = BackgroundScheduler(timezone="UTC")

    # Schedule the weekly (Monday) job
    scheduler.add_job(
        run_weekly_job,
        trigger='cron',
        day_of_week='mon',
        hour=6,  # 6:00 AM UTC
        minute=0
    )

    # Schedule the daily (Tue-Sun) job
    scheduler.add_job(
        run_daily_job,
        trigger='cron',
        day_of_week='0,2-6', # Runs on Tue, Wed, Thu, Fri, Sat, Sun
        hour=6,  # 6:00 AM UTC
        minute=0
    )

    scheduler.start()
    logger.info("Scheduler started. Waiting for jobs...")


if __name__ == "__main__":
    # This allows you to still test this script directly if needed
    print("Running scheduler in blocking mode (for testing)...")
    start_scheduler()
    try:
        # Keep the main thread alive
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        pass
