import os, random, subprocess, glob, json

os.makedirs(os.path.expanduser("~/.kaggle"), exist_ok=True)
with open(os.path.expanduser("~/.kaggle/kaggle.json"), "w") as f:
    json.dump({"username": "shreevathsbbhh", "key": "83a92caa96ed51b5d5a9a730100c57aa"}, f)
os.chmod(os.path.expanduser("~/.kaggle/kaggle.json"), 0o600)

DATASET      = "shreevathsbbhh/video-clips"
TARGET_TOTAL = 20.0
MIN_CLIP     = 3.0
MAX_CLIP     = 6.0

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
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(r.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                d = s.get("duration", 0)
                if d and float(d) > 0:
                    return float(d)
        # fallback: try format duration
        r2 = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, timeout=15
        )
        data2 = json.loads(r2.stdout)
        d = data2.get("format", {}).get("duration", 0)
        return float(d) if d else 0.0
    except:
        return 0.0

random.shuffle(all_files)
os.makedirs("clips", exist_ok=True)

segments     = []
total_so_far = 0.0
file_pool    = all_files.copy()
idx          = 0
fail_count   = 0

while total_so_far < TARGET_TOTAL:
    remaining = TARGET_TOTAL - total_so_far

    if remaining < 1.0:
        break

    if idx >= len(file_pool):
        random.shuffle(file_pool)
        idx = 0

    if fail_count > 30:
        print("Too many failures, stopping early")
        break

    f = file_pool[idx]; idx += 1
    dur = get_duration(f)
    print(f"  Checking: {os.path.basename(f)} duration={dur:.1f}s")

    if dur < MIN_CLIP:
        continue

    # Clip length — random between MIN and MAX, but never exceed remaining
    clip_len = round(random.uniform(MIN_CLIP, min(MAX_CLIP, dur - 0.5)), 2)
    clip_len = min(clip_len, remaining)
    if clip_len < 1.0:
        break

    # Random start — ensure enough room
    max_start = max(0.0, dur - clip_len - 0.5)
    start = round(random.uniform(0, max_start), 2)

    out_clip = f"clips/clip_{len(segments):04d}.mp4"

    # Re-encode every clip to IDENTICAL format — this is the key fix
    # Same resolution, same codec, same fps, same audio — guarantees clean concat
    ret = subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", f,
        "-t", str(clip_len),
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=30",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-profile:v", "baseline",
        "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        "-fflags", "+genpts",
        "-movflags", "+faststart",
        out_clip
    ], capture_output=True, text=True)

    if ret.returncode != 0:
        print(f"  Skipping {os.path.basename(f)} — encode failed")
        print(f"  Error: {ret.stderr[-300:]}")
        fail_count += 1
        continue

    # Verify clip duration
    actual_dur = get_duration(out_clip)
    if actual_dur < 0.5:
        print(f"  Skipping — output clip too short ({actual_dur}s)")
        fail_count += 1
        continue

    segments.append(out_clip)
    total_so_far += actual_dur
    fail_count = 0
    print(f"  Clip {len(segments)}: {os.path.basename(f)} | start={start}s | len={actual_dur:.2f}s | total={total_so_far:.1f}s")

print(f"\nTotal clips: {len(segments)} | Total duration: {total_so_far:.2f}s")

if not segments:
    print("No clips generated!")
    exit(1)

# Write concat list
with open("concat.txt", "w") as f:
    for clip in segments:
        f.write(f"file '{os.path.abspath(clip)}'\n")

print("Concatenating all clips...")

# Use re-encode concat — 100% reliable, no corruption
result = subprocess.run([
    "ffmpeg", "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", "concat.txt",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-ar", "44100",
    "-ac", "2",
    "-movflags", "+faststart",
    "output.mp4"
], capture_output=True, text=True)

if result.returncode != 0:
    print("Concat failed:")
    print(result.stderr[-500:])
    exit(1)

final_dur = get_duration("output.mp4")
print(f"\nDone! output.mp4 — duration: {final_dur:.2f}s")
