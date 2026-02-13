from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, Response, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import csv
import io
import subprocess
import json
from urllib.parse import urlparse, parse_qs, unquote

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


def extract_mp4_url(play_link: str) -> str | None:
    """Extract raw mp4 URL from a Newton play-video link."""
    if not play_link:
        return None

    # 1) Try proper query parsing
    try:
        parsed = urlparse(play_link)
        qs = parse_qs(parsed.query or "")
        url_vals = qs.get("url")
        if url_vals and url_vals[0]:
            return unquote(url_vals[0].strip())
    except Exception:
        pass

    # 2) Fallback: manual substring search (more forgiving)
    lower = play_link.lower()
    key = "url="
    idx = lower.find(key)
    if idx == -1:
        return None
    raw = play_link[idx + len(key) :]
    # stop at next &
    amp = raw.find("&")
    if amp != -1:
        raw = raw[:amp]
    raw = raw.strip()
    if not raw:
        return None
    return unquote(raw)


def probe_duration_seconds(mp4_url: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                mp4_url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "{}")
        duration_str = data.get("format", {}).get("duration")
        if not duration_str:
            return None
        return float(duration_str)
    except Exception:
        return None


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.post("/process")
async def process_csv(file: UploadFile = File(...)):
    # Validate content type
    if file.content_type not in ("text/csv", "application/vnd.ms-excel", "application/csv"):
        return PlainTextResponse("Please upload a CSV file.", status_code=400)

    content_bytes = await file.read()

    # Enforce 5 MB limit
    max_bytes = 5 * 1024 * 1024
    if len(content_bytes) > max_bytes:
        return PlainTextResponse("File is too large. Maximum size is 5 MB.", status_code=400)

    text = content_bytes.decode("utf-8-sig", errors="ignore")
    input_io = io.StringIO(text)
    reader = csv.reader(input_io)

    output_io = io.StringIO()
    writer = csv.writer(output_io)
    writer.writerow(["original_link", "mp4_url", "duration_seconds", "duration_minutes"])

    for row in reader:
        if not row:
            continue
        original_link = (row[0] or "").strip()
        mp4_url = extract_mp4_url(original_link) or ""

        duration_seconds = ""
        duration_minutes = ""

        if not mp4_url:
            # Help diagnose parsing issues
            duration_seconds = "no_url_parsed"
        else:
            seconds = probe_duration_seconds(mp4_url)
            if seconds is not None:
                duration_seconds = f"{seconds:.2f}"
                duration_minutes = f"{seconds / 60:.2f}"
            else:
                # ffprobe could not read this URL
                duration_seconds = "ffprobe_error"

        writer.writerow([original_link, mp4_url, duration_seconds, duration_minutes])

    output_csv = output_io.getvalue()
    return Response(
        content=output_csv,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="video_durations.csv"'
        },
    )
