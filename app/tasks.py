import logging
import os
import redis
import requests
import whisperx
import torch
import json

from app.utils import get_model, get_align_model, generate_output
from app.logging_config import init_logging

log = logging.getLogger(__name__)
redis_conn = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

MAX_CHARS_PER_LINE_EN = int(os.getenv("MAX_CHARS_PER_LINE_EN", "42"))
MAX_CHARS_PER_LINE_AR = int(os.getenv("MAX_CHARS_PER_LINE_AR", "32"))
MAX_LINES_EN = int(os.getenv("MAX_LINES_EN", os.getenv("MAX_LINES", 2)))
MAX_LINES_AR = int(os.getenv("MAX_LINES_AR", os.getenv("MAX_LINES", 2)))
MAX_LINES = int(os.getenv("MAX_LINES", 2))

def get_max_lines(language):
    language = language.lower()
    if language.startswith('en'):
        return MAX_LINES_EN
    elif language.startswith('ar'):
        return MAX_LINES_AR
    else:
        return MAX_LINES

def increment_counter(key):
    redis_conn.incr(key)

def job_success_handler(job, connection, result, *args, **kwargs):
    log.info(f"Job {job.id} completed successfully.")
    increment_counter("whisperws:jobs_completed")

def job_failure_handler(job, connection, type, value, traceback):
    log.error(f"Job {job.id} failed: {value}", exc_info=(type, value, traceback))
    increment_counter("whisperws:jobs_failed")

def generate_word_vtt(segments):
    vtt = ["WEBVTT\n"]
    for seg in segments:
        words = seg.get("words", [])
        for word in words:
            start = word.get("start")
            end = word.get("end")
            text = word.get("word", "").strip()
            if not text or start is None or end is None:
                continue
            def ts(sec):
                ms = int((sec - int(sec)) * 1000)
                h = int(sec // 3600)
                m = int((sec % 3600) // 60)
                s = int(sec % 60)
                return f"{h:02}:{m:02}:{s:02}.{ms:03}"
            vtt.append(f"{ts(start)} --> {ts(end)}\n{text}\n")
    return "\n".join(vtt).encode("utf-8")

def transcribe_task(audio_path, job_data):
    init_logging()
    from rq import get_current_job
    job = get_current_job()
    job_id = job.id if job else "unknown"

    log.info(f"Starting transcription task for job {job_id}, file: {audio_path}")
    model = get_model(job_data.get("model", "tiny"))

    try:
        audio = whisperx.load_audio(audio_path)
        result = model.transcribe(audio, batch_size=4)

        # Align timestamps
        align_model, metadata = get_align_model(result["language"])
        result = whisperx.align(result["segments"], align_model, metadata, audio, device="cpu", return_char_alignments=False)

        detected_language = result.get('language') or 'en'
        log.info(f"Detected language for job {job_id}: {detected_language}")

        if detected_language.startswith('ar'):
            max_line_width = MAX_CHARS_PER_LINE_AR
        else:
            max_line_width = MAX_CHARS_PER_LINE_EN

        max_line_count = get_max_lines(detected_language)

        final_result = {
            "text": result["text"],
            "segments": result["segments"],
            "language": job_data.get("language") or detected_language
        }

        log.info(f"Transcription successful for job {job_id}.")

        outputs = {}
        outputs["text"], _ = generate_output(
            final_result, "txt", audio_path,
            max_line_count=max_line_count,
            max_line_width=max_line_width
        )
        outputs["text"] = outputs["text"].decode("utf-8")
        outputs["vtt"], _ = generate_output(
            final_result, "vtt", audio_path,
            max_line_count=max_line_count,
            max_line_width=max_line_width
        )
        outputs["vtt"] = outputs["vtt"].decode("utf-8")
        outputs["srt"], _ = generate_output(
            final_result, "srt", audio_path,
            max_line_count=max_line_count,
            max_line_width=max_line_width
        )
        outputs["srt"] = outputs["srt"].decode("utf-8")
        outputs["words"] = generate_word_vtt(result["segments"]).decode("utf-8")
        outputs["json"] = json.dumps(
            {"segments": result["segments"], "language": final_result["language"]},
            ensure_ascii=False
        )

        response_payload = {
            "status": "done",
            "filename": job_data.get("filename", "audio"),
            "outputs": outputs,
        }

        webhook_url = job_data.get("webhook_url")
        if webhook_url:
            try:
                log.info(f"Sending webhook for job {job_id} to {webhook_url}")
                requests.post(webhook_url, json=response_payload, timeout=10)
            except Exception as e:
                log.error(f"Webhook failed for job {job_id}: {e}", exc_info=True)
                response_payload["webhook_error"] = str(e)

        return response_payload

    except Exception as e:
        log.error(f"Transcription task failed for job {job_id}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}

    finally:
        log.info(f"Cleaning up audio file for job {job_id}: {audio_path}")
        try:
            os.remove(audio_path)
        except Exception:
            pass

