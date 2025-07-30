import os
from redis import Redis
from rq import Queue
from rq.registry import FinishedJobRegistry, FailedJobRegistry, StartedJobRegistry

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
queue_name = "transcribe"

redis_conn = Redis.from_url(redis_url)
q = Queue(queue_name, connection=redis_conn)

print(f"Connected to Redis at: {redis_url}")
print(f"Resetting queue: {queue_name}")

num_pending = len(q)
q.empty()
print(f"Emptied {num_pending} pending jobs from the queue.")

total_removed = 0
for reg_cls, reg_name in [
    (FinishedJobRegistry, "FinishedJobRegistry"),
    (FailedJobRegistry, "FailedJobRegistry"),
    (StartedJobRegistry, "StartedJobRegistry"),
]:
    reg = reg_cls(queue=q)
    job_ids = reg.get_job_ids()
    for job_id in job_ids:
        reg.remove(job_id, delete_job=True)
    print(f"Removed {len(job_ids)} jobs from {reg_name}.")
    total_removed += len(job_ids)

# 3. Reset custom counters
redis_conn.set("whisperws:jobs_completed", 0)
redis_conn.set("whisperws:jobs_failed", 0)
print("Reset whisperws:jobs_completed and whisperws:jobs_failed counters to 0.")

print("\nDone. All jobs and counters have been reset.")

