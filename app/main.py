import logging
import aiofiles
import httpx
import mimetypes
import os
import uuid
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from werkzeug.utils import secure_filename
from fastapi.responses import Response
from redis import Redis
from rq import Queue
from rq.registry import FinishedJobRegistry, FailedJobRegistry, StartedJobRegistry
from app.tasks import transcribe_task, job_success_handler, job_failure_handler
from app.utils import generate_output

from app.logging_config import init_logging

init_logging()
log = logging.getLogger(__name__)

redis_conn = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "large-v3")
SHARED_DIR = os.getenv("SHARED_DIR", "/app/shared")

q = Queue(
    "transcribe",
    connection=redis_conn,
    default_timeout=int(os.getenv("DEFAULT_TIMEOUT", "1800")),
    default_result_ttl=int(os.getenv("DEFAULT_RESULT_TTL", "3600")),
)

app = FastAPI()

def get_extension(url: str, content_type: str = None) -> str:
    ext_by_type = mimetypes.guess_extension((content_type or "").split(";")[0]) if content_type else None
    ext_by_url = os.path.splitext(url)[1] if url else None
    return ext_by_type or ext_by_url or ".mp3"

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    try:
        redis_conn.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Redis connection failed")
    return {"status": "ok", "redis": "ok"}

@app.get("/metrics")
def metrics():
    finished_registry = FinishedJobRegistry(queue=q)
    failed_registry = FailedJobRegistry(queue=q)
    started_registry = StartedJobRegistry(queue=q)

    total_completed = int(redis_conn.get("whisperws:jobs_completed") or 0)
    total_failed = int(redis_conn.get("whisperws:jobs_failed") or 0)

    return {
        "queue_name": q.name,
        "pending": len(q),
        "active": len(started_registry),
        "completed": len(finished_registry),
        "failed": len(failed_registry),
        "total_completed": total_completed,
        "total_failed": total_failed,
    }

async def save_file(upload_file: UploadFile, dest_path: str):
    async with aiofiles.open(dest_path, 'wb') as out_file:
        while True:
            chunk = await upload_file.read(1024 * 1024)  # 1MB
            if not chunk:
                break
            await out_file.write(chunk)

async def fetch_file(audio_url: str, dest_path: str):
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("GET", audio_url) as response:
            response.raise_for_status()
            async with aiofiles.open(dest_path, "wb") as fobj:
                async for chunk in response.aiter_bytes(1024 * 1024):  # 1MB
                    await fobj.write(chunk)



@app.post("/v1/transcribe")
async def transcribe(
    webhook_url: str = Form(None),
    filename: str = Form("untitled"),
    language: str = Form(None),
    model: str = Form(DEFAULT_MODEL),
    task: str = Form("transcribe"),
    file: UploadFile = File(None),
    audio_url: str = Form(None),
):
    log.info(f"Received transcription request. Model: {model}, Language: {language}, Task: {task}")
    if not file and not audio_url:
        raise HTTPException(status_code=400, detail="Must provide 'file' or 'audio_url'")

    os.makedirs(SHARED_DIR, exist_ok=True)
    audio_path = None
    orig_name = None

    try:
        if file:
            file_extension = os.path.splitext(file.filename)[1] or ".mp3"
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            log.info(f"Processing transcription from uploaded file: {file.filename} -> {unique_filename}")
            audio_path = os.path.join(SHARED_DIR, unique_filename)
            await save_file(file, audio_path)
            orig_name = file.filename
        elif audio_url:
            log.info(f"Processing transcription from URL: {audio_url}")
            async with httpx.AsyncClient(timeout=15.0) as client:
                content_type = None
                try:
                    head_resp = await client.head(audio_url)
                    content_type = head_resp.headers.get("content-type", "")
                except Exception:
                    pass
            file_extension = get_extension(audio_url, content_type)
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            audio_path = os.path.join(SHARED_DIR, unique_filename)
            await fetch_file(audio_url, audio_path)
            orig_name = os.path.basename(audio_url) or "untitled"
        else:
            raise HTTPException(status_code=400, detail="Must provide 'file' or 'audio_url'")

        filename = secure_filename(filename or orig_name or "untitled")

        job_data = {
            "filename": filename,
            "language": language,
            "model": model,
            "task": task,
            "webhook_url": webhook_url,
        }

        job = q.enqueue(
            transcribe_task,
            args=[audio_path, job_data],
            result_ttl=int(os.getenv("DEFAULT_RESULT_TTL", "3600")),
            on_success=job_success_handler,
            on_failure=job_failure_handler,
        )

        log.info(f"Enqueued job {job.id} for transcription.")
        return {"job_id": job.id}
    except httpx.HTTPStatusError as e:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        log.error(f"Failed to download audio from URL {e.request.url}: {e.response.status_code}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download audio from URL: {e.request.url}. Server responded with {e.response.status_code}."
        )
    except Exception as e:
        log.error(f"An unexpected error occurred during transcription request: {e}", exc_info=True)
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        raise

@app.get("/v1/jobs")
def list_jobs(status: str = Query("pending", enum=["pending", "started", "finished", "failed"])):
    log.info(f"Request to list jobs with status: {status}")

    if status == "pending":
        job_ids = q.get_job_ids()
    elif status == "started":
        registry = StartedJobRegistry(queue=q)
        job_ids = registry.get_job_ids()
    elif status == "finished":
        registry = FinishedJobRegistry(queue=q)
        job_ids = registry.get_job_ids()
    elif status == "failed":
        registry = FailedJobRegistry(queue=q)
        job_ids = registry.get_job_ids()
    
    return {"jobs": [{"id": job_id, "status": status} for job_id in job_ids]}


@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str):
    log.debug(f"Fetching status for job {job_id}")
    job = q.fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.is_finished:
        if job.result and "error" in job.result:
            return {
                "status": "error",
                "error": job.result.get("error"),
                "filename": job.result.get("filename", "file")
            }
        return {
            "status": "done",
            "outputs": job.result.get("outputs", {}),
            "filename": job.result.get("filename", "file"),
            "webhook_error": job.result.get("webhook_error", None)
        }
    elif job.is_failed:
        return {"status": "failed", "error": str(job.exc_info)}
    else:
        return {"status": "queued or in progress"}


@app.delete("/v1/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    """
    Deletes a job from the queue, only if it is in the 'pending' status.
    """
    log.info(f"Received request to delete job {job_id}")
    job = q.fetch_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    if job.get_status() == 'queued':
        log.info(f"Job {job_id} is pending. Deleting...")
        job.delete()
        log.info(f"Successfully deleted job {job_id}")
        return Response(status_code=204)
    else:
        log.warning(f"Attempted to delete job {job_id} which is not pending. Status: {job.get_status()}")
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} cannot be deleted because its status is '{job.get_status()}'. Only pending jobs can be deleted."
        )

@app.get("/v1/download/{job_id}")
def download(job_id: str, output: str = "vtt"):
    log.info(f"Request to download job {job_id} with format {output}")
    job = q.fetch_job(job_id)
    if not job or not job.is_finished or not job.result:
        raise HTTPException(status_code=404, detail="Job not ready or does not exist")

    outputs = job.result.get("outputs")
    key = "text" if output == "txt" else output
    if not outputs or key not in outputs:
        raise HTTPException(status_code=404, detail=f"Output format '{output}' not found for this job")

    content = outputs[key]

    if output == "txt" or output == "text":
        mime = "text/plain"
    elif output == "json":
        mime = "application/json"
    elif output == "vtt":
        mime = "text/vtt"
    elif output == "srt":
        mime = "application/x-subrip"
    elif output == "words":
        mime = "text/vtt"
    else:
        mime = "application/octet-stream"

    filename = f"{job.result.get('filename', 'file')}.{output}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return Response(content, media_type=mime, headers=headers)
