import os
import redis
import threading
import scheduler  # <-- Import your scheduler script
from rq import Worker, Queue

# Get the Redis URL from the environment variable
redis_url = os.getenv('REDIS_URL')
if not redis_url:
    raise RuntimeError("REDIS_URL environment variable not set.")

# Set the queues this worker will listen to
listen = ['default']

conn = redis.from_url(redis_url)

def run_scheduler_in_background():
    """
    Wrapper to run the scheduler logic in a separate thread.
    """
    print("Starting background scheduler thread...")
    scheduler.start_scheduler()

if __name__ == '__main__':

    # --- Start the Scheduler Thread ---
    # We run the scheduler in a daemon thread.
    # This means it will exit automatically when the main worker process stops.
    scheduler_thread = threading.Thread(target=run_scheduler_in_background, daemon=True)
    scheduler_thread.start()

    # --- Start the Main RQ Worker ---
    # This is the original code that listens for on-demand jobs.
    # It will block the main thread, which is what we want.
    q = Queue(connection=conn)
    worker = Worker([q], connection=conn)

    print(f"RQ Worker starting, listening on queue: {listen[0]}")
    worker.work()
