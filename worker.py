import os
import redis
from rq import Worker, Queue

# Get the Redis URL from the environment variable
redis_url = os.getenv('REDIS_URL')
if not redis_url:
    raise RuntimeError("REDIS_URL environment variable not set.")

# Set the queues this worker will listen to
listen = ['default']

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    # Create the Queue and Worker, passing the connection directly
    q = Queue(connection=conn)
    worker = Worker([q], connection=conn)

    # Start the worker
    print(f"Worker starting, listening on queue: {listen[0]}")
    worker.work()
