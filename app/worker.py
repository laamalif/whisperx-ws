import os
import logging
from redis import Redis
from rq import Worker, Queue
from app.logging_config import init_logging

listen = ['transcribe']
redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
conn = Redis.from_url(redis_url)
default_job_timeout = int(os.getenv("DEFAULT_TIMEOUT", "1200"))

if __name__ == '__main__':
    init_logging()
    log = logging.getLogger(__name__)
    log.info(f"Starting worker with default_job_timeout={default_job_timeout}")
    queues = [Queue(name, connection=conn) for name in listen]
    worker = Worker(queues, connection=conn, default_job_timeout=default_job_timeout)
    worker.work()
