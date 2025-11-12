import os
import redis
from rq import Worker, Queue, Connection

# Get the Redis URL from the environment variable we set
redis_url = os.getenv('REDIS_URL')
if not redis_url:
    raise RuntimeError("REDIS_URL environment variable not set.")

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    with Connection(conn):
        # We tell the worker to listen on the 'default' queue
        worker = Worker(Queue('default'))
        worker.work()
