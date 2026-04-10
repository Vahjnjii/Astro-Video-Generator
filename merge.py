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

    # source_extract = half of desired output (slowmo 0.5x doubles duration)
    # so we need at least MIN_CLIP/2 seconds available in the source
    if dur < (MIN_CLIP / 2.0) + 0.5:
        fails += 1
        continue

    desired_len    = round(random.uniform(MIN_CLIP, min(MAX_CLIP, remaining)), 2)
    source_extract = round(desired_len / 2.0, 2)

    # Pick from center 80% of clip
    center_start = dur * 0.10
    center_end   = dur * 0.90
    center_len   = center_end - center_start

    if source_extract <= center_len:
        max_start = center_end - source_extract
        start = round(random.uniform(center_start, max_start), 2)
    elif source_extract <= dur - 0.5:
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

# --- Step 1: Process each clip individually into a temp file ---
# This avoids complex filter_complex sync issues with slowmo + concat
temp_files = []

for i, (f, start, source_extract, desired_len) in enumerate(segments):
    tmp = f"temp_seg_{i}.mp4"
    temp_files.append(tmp)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t",  str(source_extract),
        "-i",  f,
        "-vf", (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={FPS},"
            f"setsar=1,"
            f"setpts=2.0*PTS"       # slow video to 0.5x
        ),
        "-af", "aresample=44100,atempo=0.5",   # slow audio to match video
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf",  "22",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar",  "44100",
        "-ac",  "2",
        tmp
    ]

    print(f"Processing segment {i+1}/{len(segments)}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Segment {i} failed: {result.stderr[-500:]}")
        exit(1)

# --- Step 2: Concat all temp files using concat demuxer ---
list_file = "concat_list.txt"
with open(list_file, "w") as lf:
    for tmp in temp_files:
        lf.write(f"file '{tmp}'\n")

print("\nConcatenating all segments...")
concat_cmd = [
    "ffmpeg", "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", list_file,
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
    "output_with_audio.mp4"
]

result = subprocess.run(concat_cmd, capture_output=True, text=True)
if result.returncode != 0:
    print("Concat failed!")
    print(result.stderr[-2000:])
    exit(1)

# --- Step 3: Mute audio by replacing with silent track ---
# Replacing audio AFTER concat ensures video duration is correct
print("\nMuting audio...")
mute_cmd = [
    "ffmpeg", "-y",
    "-i", "output_with_audio.mp4",
    "-f", "lavfi",
    "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
    "-c:v", "copy",          # copy video stream — no re-encode
    "-c:a", "aac",
    "-b:a", "128k",
    "-shortest",             # match duration to video stream
    "-movflags", "+faststart",
    "output.mp4"
]

result = subprocess.run(mute_cmd, capture_output=True, text=True)
if result.returncode != 0:
    print("Mute step failed!")
    print(result.stderr[-2000:])
    exit(1)

# Cleanup temp files
for tmp in temp_files:
    try: os.remove(tmp)
    except: pass
try: os.remove("output_with_audio.mp4")
except: pass
try: os.remove(list_file)
except: pass

final = get_duration("output.mp4")
size  = os.path.getsize("output.mp4") / (1024*1024)
print(f"\nDone! output.mp4 — {final:.2f}s — {size:.1f}MB")
