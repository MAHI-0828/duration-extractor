# Video Duration Extractor

Simple FastAPI tool to read a CSV of Newton School `play-video` links, extract MP4 URLs, run `ffprobe` to get video duration, and return a CSV with durations.

## Requirements

- Python 3.10+ recommended
- `ffprobe` installed and available on `PATH` (part of `ffmpeg`)

### Install ffmpeg/ffprobe

**Windows (Chocolatey)**

```powershell
choco install ffmpeg
```

**Windows (scoop)**

```powershell
scoop install ffmpeg
```

**macOS (Homebrew)**

```bash
brew install ffmpeg
```

**Debian/Ubuntu**

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

Verify:

```bash
ffprobe -version
```

## Setup

From the project directory:

```bash
pip install -r requirements.txt
```

## Run the app

```bash
uvicorn app:app --reload
```

Open your browser at `http://127.0.0.1:8000/`.

## Usage

1. Prepare a CSV where the **first column** contains links like:

   ```text
   https://my.newtonschool.co/play-video/?url=https://cloudfront/...mp4
   ```

   Other columns (if present) are ignored.

2. Go to `http://127.0.0.1:8000/`.
3. Upload the CSV and submit.
4. Your browser will download an output CSV with columns:

   - `original_link`
   - `mp4_url`
   - `duration_seconds`
   - `duration_minutes`

Rows with invalid links or `ffprobe` errors will have empty duration fields, but other rows will still be processed.

