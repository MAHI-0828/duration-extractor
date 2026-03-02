from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
import uuid, os, csv, io, json, asyncio, signal
from urllib.parse import urlparse, parse_qs, unquote

app = FastAPI()

BASE = "jobs"
os.makedirs(BASE, exist_ok=True)

MAX_CONCURRENT_PROBES = 5
PROBE_TIMEOUT = 25


# ---------- URL ----------
def extract_mp4_url(link: str):
    if not link: return None
    try:
        qs = parse_qs(urlparse(link).query)
        if "url" in qs:
            return unquote(qs["url"][0])
    except:
        pass
    if "url=" in link:
        return unquote(link.split("url=")[1].split("&")[0])
    return None


# ---------- FFPROBE ----------
async def probe(url, sem):
    async with sem:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe","-v","error",
                "-rw_timeout","15000000",
                "-timeout","15000000",
                "-show_entries","format=duration",
                "-of","json",url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid
            )

            try:
                out,_ = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
            except asyncio.TimeoutError:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                return "timeout",""

            if proc.returncode!=0: return "ffprobe_error",""

            d=json.loads(out.decode() or "{}").get("format",{}).get("duration")
            if not d: return "no_duration",""
            d=float(d)
            return f"{d:.2f}",f"{d/60:.2f}"
        except:
            return "ffprobe_crash",""


# ---------- WORKER ----------
async def process_job(job_id, path):
    status_path=f"{BASE}/{job_id}/status.json"
    out_path=f"{BASE}/{job_id}/result.csv"

    with open(path) as f:
        reader=csv.DictReader(f)
        reader.fieldnames=[c.strip().lower().replace(" ","_") for c in reader.fieldnames]
        rows=list(reader)

    sem=asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    parsed=[]
    tasks=[]
    for r in rows:
        lid=(r.get("lecture_id") or "")
        link=(r.get("play_link") or r.get("link") or r.get("url") or "")
        mp4=extract_mp4_url(link) or ""
        parsed.append((lid,link,mp4))
        tasks.append(probe(mp4,sem) if mp4 else asyncio.sleep(0,result=("no_url_parsed","")))

    results=[]
    for i,t in enumerate(asyncio.as_completed(tasks)):
        res=await t
        results.append(res)
        with open(status_path,"w") as s:
            json.dump({"done":len(results),"total":len(tasks)},s)

    with open(out_path,"w",newline="") as f:
        w=csv.writer(f)
        w.writerow(["lecture_id","original_link","mp4_url","duration_seconds","duration_minutes"])
        for (lid,link,mp4),(sec,minu) in zip(parsed,results):
            w.writerow([lid,link,mp4,sec,minu])


# ---------- UPLOAD ----------
@app.post("/upload")
async def upload(file:UploadFile=File(...)):
    if not file.filename.endswith(".csv"):
        return PlainTextResponse("upload csv",400)

    job=str(uuid.uuid4())
    job_dir=f"{BASE}/{job}"
    os.makedirs(job_dir)

    path=f"{job_dir}/input.csv"
    with open(path,"wb") as f:
        f.write(await file.read())

    open(f"{job_dir}/status.json","w").write('{"done":0,"total":1}')

    asyncio.create_task(process_job(job,path))

    return {"job_id":job}


# ---------- STATUS ----------
@app.get("/status/{job}")
def status(job:str):
    p=f"{BASE}/{job}/status.json"
    if not os.path.exists(p): return {"error":"invalid job"}
    return json.load(open(p))


# ---------- DOWNLOAD ----------
@app.get("/download/{job}")
def download(job:str):
    p=f"{BASE}/{job}/result.csv"
    if not os.path.exists(p): return {"error":"not ready"}
    return FileResponse(p,filename="video_durations.csv")
