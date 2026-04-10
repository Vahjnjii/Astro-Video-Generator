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
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
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
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
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

    if dur < (MIN_CLIP / 2.0) + 0.5:
        fails += 1
        continue

    desired_len    = round(random.uniform(MIN_CLIP, min(MAX_CLIP, remaining)), 2)
    source_extract = round(desired_len / 2.0, 2)

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
          f"start={start:.2f}s | extract={source_extract:.2f}s | "
          f"after_slowmo={desired_len:.2f}s | total={total_dur:.1f}s")

print(f"\nTotal segments: {len(segments)} | Total after slowmo: {total_dur:.2f}s")

if not segments:
    print("No segments found!")
    exit(1)


# ---------------------------------------------------------------
# Step 1: For each clip, use filter_complex to:
#   - Take video from input file
#   - Generate silence from anullsrc
#   - Scale, pad, fps, slow video (setpts=2.0*PTS)
#   - Encode both video + silent audio into temp file
#   Using filter_complex avoids ALL stream index ambiguity
# ---------------------------------------------------------------
temp_files = []

for i, (f, start, source_extract, desired_len) in enumerate(segments):
    tmp = f"temp_seg_{i}.mp4"
    temp_files.append(tmp)

    filter_complex = (
        # Video chain: scale → pad → fps → setsar → slow to 0.5x
        f"[0:v]"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={FPS},"
        f"setsar=1,"
        f"setpts=2.0*PTS"
        f"[vout];"
        # Silent audio from anullsrc (input 1), trimmed to exact slowed duration
        f"[1:a]atrim=0:{desired_len},asetpts=PTS-STARTPTS[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t",  str(source_extract),
        "-i",  f,                                    # input 0: video file
        "-f",  "lavfi",
        "-i",  "anullsrc=channel_layout=stereo:sample_rate=44100",  # input 1: silence
        "-filter_complex", filter_complex,
        "-map", "[vout]",                            # map processed video
        "-map", "[aout]",                            # map silence
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar",  "44100",
        "-ac",  "2",
        tmp
    ]

    print(f"Processing segment {i+1}/{len(segments)}: {os.path.basename(f)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Segment {i+1} failed!\n{result.stderr[-1000:]}")
        exit(1)

    actual = get_duration(tmp)
    print(f"  → temp duration: {actual:.2f}s (expected ~{desired_len:.2f}s)")

    # Verify video stream exists in temp file
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", tmp],
        capture_output=True, text=True
    )
    streams = json.loads(r.stdout).get("streams", [])
    has_v = any(s.get("codec_type") == "video" for s in streams)
    has_a = any(s.get("codec_type") == "audio" for s in streams)
    print(f"  → streams: video={has_v} audio={has_a}")
    if not has_v:
        print(f"ERROR: No video stream in temp segment {i+1}!")
        exit(1)


# ---------------------------------------------------------------
# Step 2: Concat all temp files using concat demuxer
#   All files are same codec/res/fps — stream copy is safe
# ---------------------------------------------------------------
list_file = "concat_list.txt"
with open(list_file, "w") as lf:
    for tmp in temp_files:
        lf.write(f"file '{os.path.abspath(tmp)}'\n")

print("\nConcatenating segments...")
concat_cmd = [
    "ffmpeg", "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", list_file,
    "-c", "copy",
    "-movflags", "+faststart",
    "output.mp4"
]

result = subprocess.run(concat_cmd, capture_output=True, text=True)
if result.returncode != 0:
    print("Concat failed!")
    print(result.stderr[-2000:])
    exit(1)

# Cleanup
for tmp in temp_files:
    try: os.remove(tmp)
    except: pass
try: os.remove(list_file)
except: pass

final = get_duration("output.mp4")
size  = os.path.getsize("output.mp4") / (1024 * 1024)
print(f"\nDone! output.mp4 — {final:.2f}s — {size:.1f}MB")
