from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, Response, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import csv
import io
import json
import asyncio
from urllib.parse import urlparse, parse_qs, unquote

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# max parallel ffprobe processes
MAX_CONCURRENT_PROBES = 8
PROBE_TIMEOUT = 45


# ---------------- URL PARSER ----------------
def extract_mp4_url(play_link: str) -> str | None:
    if not play_link:
        return None

    try:
        parsed = urlparse(play_link)
        qs = parse_qs(parsed.query or "")
        url_vals = qs.get("url")
        if url_vals and url_vals[0]:
            return unquote(url_vals[0].strip())
    except Exception:
        pass

    lower = play_link.lower()
    key = "url="
    idx = lower.find(key)
    if idx == -1:
        return None

    raw = play_link[idx + len(key):]
    amp = raw.find("&")
    if amp != -1:
        raw = raw[:amp]

    raw = raw.strip()
    return unquote(raw) if raw else None


# ---------------- ASYNC FFPROBE ----------------
async def probe_duration_seconds_async(mp4_url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                mp4_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=PROBE_TIMEOUT
                )
            except asyncio.TimeoutError:
                process.kill()
                return "timeout", ""

            if process.returncode != 0:
                return "ffprobe_error", ""

            data = json.loads(stdout.decode() or "{}")
            duration_str = data.get("format", {}).get("duration")
            if not duration_str:
                return "no_duration", ""

            seconds = float(duration_str)
            return f"{seconds:.2f}", f"{seconds/60:.2f}"

        except Exception:
            return "ffprobe_crash", ""


# ---------------- PAGE ----------------
@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


# ---------------- CSV PROCESS ----------------
@app.post("/process")
async def process_csv(file: UploadFile = File(...)):
    if file.content_type not in (
        "text/csv",
        "application/vnd.ms-excel",
        "application/csv"
    ):
        return PlainTextResponse("Please upload a CSV file.", status_code=400)

    content_bytes = await file.read()

    if len(content_bytes) > 5 * 1024 * 1024:
        return PlainTextResponse("File is too large. Maximum size is 5 MB.", status_code=400)

    text = content_bytes.decode("utf-8-sig", errors="ignore")
    input_io = io.StringIO(text)

    # ---- Normalize headers ----
    reader = csv.DictReader(input_io)
    reader.fieldnames = [
        name.strip().lower().replace(" ", "_")
        for name in reader.fieldnames
    ]

    rows = list(reader)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)
    tasks = []

    parsed_rows = []

    for row in rows:
        lecture_id = (row.get("lecture_id") or "").strip()
        original_link = (
            row.get("play_link")
            or row.get("link")
            or row.get("url")
            or ""
        ).strip()

        mp4_url = extract_mp4_url(original_link) or ""

        parsed_rows.append((lecture_id, original_link, mp4_url))

        if mp4_url:
            tasks.append(probe_duration_seconds_async(mp4_url, semaphore))
        else:
            tasks.append(asyncio.sleep(0, result=("no_url_parsed", "")))

    results = await asyncio.gather(*tasks)

    # ---- Write Output ----
    output_io = io.StringIO()
    writer = csv.writer(output_io)

    writer.writerow([
        "lecture_id",
        "original_link",
        "mp4_url",
        "duration_seconds",
        "duration_minutes"
    ])

    for (lecture_id, original_link, mp4_url), (sec, mins) in zip(parsed_rows, results):
        writer.writerow([lecture_id, original_link, mp4_url, sec, mins])

    return Response(
        content=output_io.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="video_durations.csv"'}
    )
