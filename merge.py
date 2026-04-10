import os, random, subprocess, glob, json

os.makedirs(os.path.expanduser("~/.kaggle"), exist_ok=True)
with open(os.path.expanduser("~/.kaggle/kaggle.json"), "w") as f:
    json.dump({"username": "shreevathsbbhh", "key": "83a92caa96ed51b5d5a9a730100c57aa"}, f)
os.chmod(os.path.expanduser("~/.kaggle/kaggle.json"), 0o600)

DATASET      = "shreevathsbbhh/video-clips"
TARGET_TOTAL = 20.0
MIN_CLIP     = 3.0
MAX_CLIP     = 6.0
WIDTH        = 1280
HEIGHT       = 720
FPS          = 30

os.makedirs("videos", exist_ok=True)
print("Downloading dataset...")
subprocess.run(
    ["kaggle", "datasets", "download", "-d", DATASET, "-p", "videos", "--unzip"],
    check=True
)

exts = ("*.mp4","*.MP4","*.mkv","*.avi","*.mov","*.webm","*.flv","*.wmv")
all_files = []
for ext in exts:
    all_files.extend(glob.glob(f"videos/**/{ext}", recursive=True))
    all_files.extend(glob.glob(f"videos/{ext}"))
all_files = list(set(all_files))

if not all_files:
    print("No video files found!")
    exit(1)

print(f"Found {len(all_files)} video files")

def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_format","-show_streams", path],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(r.stdout)
        # Try video stream first
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                d = s.get("duration")
                if d and float(d) > 0:
                    return float(d)
        # Fallback to format
        d = data.get("format", {}).get("duration")
        return float(d) if d else 0.0
    except:
        return 0.0

def is_valid_video(path):
    try:
        r = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_streams", path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        has_video = any(s.get("codec_type") == "video" for s in data.get("streams", []))
        return has_video
    except:
        return False

random.shuffle(all_files)

# Build list of (file, start, duration) segments until we reach 20s
segments   = []
total_dur  = 0.0
pool       = all_files.copy()
idx        = 0
fails      = 0

while total_dur < TARGET_TOTAL:
    remaining = TARGET_TOTAL - total_dur
    if remaining < 1.0:
        break
    if fails > 40:
        print("Too many failures, stopping")
        break
    if idx >= len(pool):
        random.shuffle(pool)
        idx = 0

    f = pool[idx]; idx += 1

    if not is_valid_video(f):
        fails += 1
        continue

    dur = get_duration(f)
    if dur < MIN_CLIP:
        fails += 1
        continue

    clip_len = round(random.uniform(MIN_CLIP, min(MAX_CLIP, dur - 0.3)), 2)
    clip_len = min(clip_len, remaining)
    if clip_len < 1.0:
        break

    max_start = max(0.0, dur - clip_len - 0.3)
    start     = round(random.uniform(0, max_start), 2)

    segments.append((f, start, clip_len))
    total_dur += clip_len
    print(f"  Segment {len(segments)}: {os.path.basename(f)} | start={start}s | len={clip_len}s | total={total_dur:.1f}s")
    fails = 0

print(f"\nTotal segments: {len(segments)} | Total: {total_dur:.2f}s")

if not segments:
    print("No segments found!")
    exit(1)

# Build FFmpeg command using filter_complex concat
# This handles ALL format differences — no pre-processing needed
# Each input gets trimmed and normalized inside one single FFmpeg call

inputs = []
filter_parts = []

for i, (f, start, clip_len) in enumerate(segments):
    inputs += ["-ss", str(start), "-t", str(clip_len), "-i", f]
    filter_parts.append(
        f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={FPS},"
        f"setsar=1,"
        f"setpts=PTS-STARTPTS[v{i}];"
        f"[{i}:a]aresample=44100,asetpts=PTS-STARTPTS[a{i}];"
    )

n = len(segments)
v_inputs = "".join(f"[v{i}]" for i in range(n))
a_inputs = "".join(f"[a{i}]" for i in range(n))
filter_complex = (
    "".join(filter_parts) +
    f"{v_inputs}concat=n={n}:v=1:a=0[vout];" +
    f"{a_inputs}concat=n={n}:v=0:a=1[aout]"
)

cmd = (
    ["ffmpeg", "-y"] +
    inputs +
    [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        "output.mp4"
    ]
)

print("\nRunning FFmpeg filter_complex concat...")
result = subprocess.run(cmd, capture_output=True, text=True)

if result.returncode != 0:
    print("FFmpeg failed!")
    print(result.stderr[-1000:])
    exit(1)

final = get_duration("output.mp4")
size  = os.path.getsize("output.mp4") / (1024*1024)
print(f"\nDone! output.mp4 — {final:.2f}s — {size:.1f}MB")
