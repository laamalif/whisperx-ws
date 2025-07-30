import os
import json
import torch
import whisperx
import threading

_models = {}
_alignment_models = {}
_model_lock = threading.Lock()

def get_model(name=None):
    if name is None:
        name = os.getenv("DEFAULT_MODEL", "large-v3")
    with _model_lock:
        if name not in _models:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if torch.cuda.is_available() else "int8"
            _models[name] = whisperx.load_model(name, device, compute_type=compute_type)
        return _models[name]

def get_alignment_model(language_code):
    with _model_lock:
        if language_code not in _alignment_models:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model, metadata = whisperx.load_align_model(language_code=language_code, device=device)
            _alignment_models[language_code] = (model, metadata)
        return _alignment_models[language_code]



def format_timestamp(seconds, separator='.'):
    """Formats a timestamp into HH:MM:SS,ms format."""
    milliseconds = int(seconds * 1000)
    hours = milliseconds // 3600000
    milliseconds %= 3600000
    minutes = milliseconds // 60000
    milliseconds %= 60000
    seconds = milliseconds // 1000
    milliseconds %= 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"

def generate_segment_srt(segments):
    """Generates an SRT file from transcription segments."""
    lines = []
    for i, seg in enumerate(segments):
        start = format_timestamp(seg['start'], separator=',')
        end = format_timestamp(seg['end'], separator=',')
        lines.append(str(i + 1))
        lines.append(f"{start} --> {end}")
        lines.append(seg['text'].strip())
        lines.append("")
    return "\n".join(lines).encode("utf-8")

def generate_word_vtt(segments):
    """Generates a word-level VTT file."""
    lines = ["WEBVTT\n"]
    for seg in segments:
        for word in seg.get("words", []):
            start = format_timestamp(word['start'], separator='.')
            end = format_timestamp(word['end'], separator='.')
            lines.append(f"{start} --> {end}")
            lines.append(word['word'].strip())
            lines.append("")
    return "\n".join(lines).encode("utf-8")

def generate_output(result, format="vtt", audio_path=None):
    segments = result.get("segments", [])

    if format == "txt":
        return result.get("text", "").encode("utf-8"), "text/plain"

    elif format == "json":
        # The result from whisperx is already a rich dictionary
        return json.dumps(result, indent=2).encode("utf-8"), "application/json"

    elif format == "srt":
        return generate_segment_srt(segments), "application/x-subrip"

    elif format == "vtt_words":
        return generate_word_vtt(segments), "text/vtt"

    else:
        return None, None