# WhisperX-WS: A WhisperX-Powered Transcription API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

WhisperX-WS is a high-performance, asynchronous web service for audio transcription using the [WhisperX](https://github.com/m-bain/whisperx) library. It provides a robust and scalable API for transcribing audio and video files, with features like language detection, job queuing, and webhook notifications.

## Features

- **Accurate Transcription with Word-Level Timestamps**: Leverages WhisperX for precise transcriptions with detailed, word-level timing information.
- **Multiple Output Formats**: Get your transcription in various formats, including plain text (`txt`), segment-level subtitles (`vtt`, `srt`), detailed `json`, and word-level subtitles (`words`).
- **Wide Format Support**: Handles any audio or video file format readable by ffmpeg (e.g., mp3, wav, flac, mp4, m4a, ogg, webm, mov).
- **Automatic Audio Extraction**: For video files, the audio track is automatically extracted for transcription.
- **Flexible Model Selection**: Choose from any installed Whisper model (`tiny`, `base`, `small`, `medium`, `large-v3`, etc.) to balance speed and accuracy.
- **Job Queuing**: Manages transcription jobs asynchronously using a Redis-backed queue.
- **Webhook Notifications**: Notifies your application when a transcription job is complete.
- **Easy to Deploy**: Can be deployed in minutes using Docker and Docker Compose.

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)
- NVIDIA GPU drivers (for GPU acceleration)

### Running the Service

1.  Clone the repository:
    ```bash
    git clone https://github.com/laamalif/whisperx-ws.git
    cd whisperx-ws
    ```
2.  Build and run the services using Docker Compose:
    ```bash
    docker-compose up --build
    ```

The API will be available at `http://localhost:8000`.

---

## Configuration

You can customize the behavior of the output by modifying the environment variables in the `docker-compose.yml` file. The following variables are available for the `worker` service:

| Variable                  | Default | Description |
|---------------------------|---------|-------------|
| `MAX_LINES_EN`            | `2`     | The maximum number of lines per subtitle segment for English. |
| `MAX_LINES_AR`            | `2`     | The maximum number of lines per subtitle segment for Arabic. |
| `MAX_CHARS_PER_LINE_EN`   | `42`    | (Commented out by default) The maximum number of characters per line for English subtitles. |
| `MAX_CHARS_PER_LINE_AR`   | `32`    | (Commented out by default) The maximum number of characters per line for Arabic subtitles. |
| `DEFAULT_MODEL`           | `medium`| The default WhisperX model to use for transcriptions if not specified in the API call. |

---

## API Reference



### 2. Transcribe Audio

Submits a new transcription job.

**Endpoint:** `POST /v1/transcribe`  
**Content-Type:** `multipart/form-data`

**Parameters:**

| Name        | Type | Description |
|-------------|------|-------------|
| `file`        | file | The audio file to transcribe. |
| `audio_url`   | str  | The URL of the audio file to transcribe. |
| `filename`    | str  | A custom name for the file. |
| `language`    | str  | The language of the audio (e.g., `en`, `ar`). If omitted, auto-detection is used. |
| `model`       | str  | The Whisper model to use. Default: `large-v3`. |
| `task`        | str  | The task to perform (`transcribe` or `translate`). Default: `transcribe`. |
| `webhook_url` | str  | A URL to be called with the job result upon completion. |

#### Example
```bash
curl -X POST "http://localhost:8000/v1/transcribe" \
     -F "file=@/path/to/your/audio.mp3" \
     -F "filename=my_custom_audio" \
     -F "model=large-v3" \
     -F "language=ar" \
     -F "webhook_url=https://your-webhook-receiver.com/hook"
```

---

### 3. Manage Jobs

#### Get Job Status

Retrieves the status and result of a specific transcription job.

**Endpoint:** `GET /v1/jobs/{job_id}`

**Example:**
```bash
curl http://localhost:8000/v1/jobs/your-job-id-here
```

#### List Jobs by Status

Lists all job IDs for a given status.

**Endpoint:** `GET /v1/jobs`

**Query Parameters:**

| Name   | Type | Description |
|--------|------|-------------|
| `status` | str  | The job status to filter by (`pending`, `started`, `finished`, `failed`). Default: `pending`. |

**Example:**
```bash
curl "http://localhost:8000/v1/jobs?status=pending"
```

#### Delete a Pending Job

Deletes a job from the queue, but only if it is still in `pending` status.

**Endpoint:** `DELETE /v1/jobs/{job_id}`

**Example:**
```bash
curl -X DELETE "http://localhost:8000/v1/jobs/your-job-id-here"
```

---

### 4. Download Transcription

Downloads the transcription result in a specific format.

**Endpoint:** `GET /v1/download/{job_id}`

**Query Parameters:**

| Name   | Type | Description |
|--------|------|-------------|
| `output` | str  | The desired output format (`txt`, `vtt`, `srt`, `json`, `words`). Default: `vtt`. |

**Examples:**

Download SRT (Segment-level):
```bash
curl -o "transcription.srt" \
     "http://localhost:8000/v1/download/your-job-id-here?output=srt"
```

Download VTT (Word-level):
```bash
curl -o "transcription.words.vtt" \
     "http://localhost:8000/v1/download/your-job-id-here?output=words"
```

---

## Monitoring

### Health Check

Checks the health of the service and its connection to Redis.

**Endpoint:** `GET /health`

**Example:**
```bash
curl http://localhost:8000/health
```

### Metrics

Provides metrics about the job queue.

**Endpoint:** `GET /metrics`

**Example:**
```bash
curl http://localhost:8000/metrics
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
