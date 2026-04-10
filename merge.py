import os, random, subprocess, glob, json

os.makedirs(os.path.expanduser("~/.kaggle"), exist_ok=True)
with open(os.path.expanduser("~/.kaggle/kaggle.json"), "w") as f:
    json.dump({"username": "shreevathsbbhh", "key": "83a92caa96ed51b5d5a9a730100c57aa"}, f)
os.chmod(os.path.expanduser("~/.kaggle/kaggle.json"), 0o600)

DATASET      = "shreevathsbbhh/video-clips"
TARGET_TOTAL = 20.0
MIN_CLIP     = 3.0
MAX_CLIP     = 7.0
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
            ["ffprobe","-v","quiet","-print_format","json",
             "-show_format","-show_streams", path],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(r.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                d = s.get("duration")
                if d and float(d) > 0:
                    return float(d)
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
        return any(s.get("codec_type") == "video" for s in data.get("streams", []))
    except:
        return False

random.shuffle(all_files)

segments  = []
total_dur = 0.0
pool      = all_files.copy()
idx       = 0
fails     = 0

while total_dur < TARGET_TOTAL:
    remaining = TARGET_TOTAL - total_dur
    if remaining < 1.0:
        break
    if fails > 50:
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

    # Need at least MIN_CLIP/2 seconds in source because slowmo doubles it
    if dur < (MIN_CLIP / 2.0) + 0.5:
        fails += 1
        continue

    # desired output duration after slowmo, capped to remaining
    desired_len = round(random.uniform(MIN_CLIP, min(MAX_CLIP, remaining)), 2)

    # extract half the duration from source — setpts=2.0 will double it
    source_extract = round(desired_len / 2.0, 2)

    # Try to pick from center 80% of clip for cleaner cuts
    center_start = dur * 0.10
    center_end   = dur * 0.90
    center_len   = center_end - center_start

    if source_extract <= center_len:
        max_start = center_end - source_extract
        start = round(random.uniform(center_start, max_start), 2)
    elif source_extract <= dur - 0.5:
        # fallback: use full clip range
        start = round(random.uniform(0.0, dur - source_extract - 0.3), 2)
    else:
        fails += 1
        continue

    segments.append((f, start, source_extract, desired_len))
    total_dur += desired_len
    fails = 0
    print(f"  Segment {len(segments)}: {os.path.basename(f)} | "
          f"source_start={start:.2f}s | extract={source_extract:.2f}s | "
          f"after_slowmo={desired_len:.2f}s | total={total_dur:.1f}s")

print(f"\nTotal segments: {len(segments)} | Total after slowmo: {total_dur:.2f}s")

if not segments:
    print("No segments found!")
    exit(1)

inputs       = []
filter_parts = []

for i, (f, start, source_extract, desired_len) in enumerate(segments):
    inputs += ["-ss", str(start), "-t", str(source_extract), "-i", f]

    filter_parts.append(
        # Video: scale → pad → fps → setsar → slow to 0.5x speed → reset pts
        f"[{i}:v]"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={FPS},"
        f"setsar=1,"
        f"setpts=2.0*PTS,"
        f"setpts=PTS-STARTPTS"
        f"[v{i}];"

        # Audio: resample → mute completely (no atempo needed since audio is muted)
        f"[{i}:a]"
        f"aresample=44100,"
        f"volume=0,"
        f"asetpts=PTS-STARTPTS"
        f"[a{i}];"
    )

n        = len(segments)
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

print("\nRunning FFmpeg...")
result = subprocess.run(cmd, capture_output=True, text=True)

if result.returncode != 0:
    print("FFmpeg failed!")
    print(result.stderr[-3000:])
    exit(1)

final = get_duration("output.mp4")
size  = os.path.getsize("output.mp4") / (1024*1024)
print(f"\nDone! output.mp4 — {final:.2f}s — {size:.1f}MB")
