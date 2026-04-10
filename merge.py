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
            ["ffprobe","-v","quiet","-print_format","json","-show_streams", path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                return float(s.get("duration", 0))
    except:
        pass
    return 0.0

random.shuffle(all_files)
os.makedirs("clips", exist_ok=True)

segments     = []
total_so_far = 0.0
file_pool    = all_files.copy()
idx          = 0

while total_so_far < TARGET_TOTAL:
    remaining = TARGET_TOTAL - total_so_far

    if idx >= len(file_pool):
        random.shuffle(file_pool)
        idx = 0

    f = file_pool[idx]; idx += 1
    dur = get_duration(f)
    if dur < MIN_CLIP:
        continue

    max_possible = min(MAX_CLIP, dur, remaining + MAX_CLIP)
    clip_len = round(random.uniform(MIN_CLIP, max(MIN_CLIP, max_possible)), 2)

    if total_so_far + clip_len > TARGET_TOTAL + 0.5:
        clip_len = round(remaining, 2)
        if clip_len < 1.0:
            break

    max_start = max(0, dur - clip_len - 0.5)
    start = round(random.uniform(0, max_start), 2)

    out_clip = f"clips/clip_{len(segments):04d}.mp4"

    ret = subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", f,
        "-t", str(clip_len),
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-avoid_negative_ts", "make_zero",
        out_clip
    ], capture_output=True)

    if ret.returncode != 0:
        print(f"Skipping {os.path.basename(f)} (encode failed)")
        continue

    segments.append(out_clip)
    total_so_far += clip_len
    print(f"Clip {len(segments)}: {os.path.basename(f)} | start={start}s | len={clip_len}s | total={total_so_far:.1f}s")

print(f"\nUsing {len(segments)} clips — total: {total_so_far:.2f}s")

with open("concat.txt", "w") as f:
    for clip in segments:
        f.write(f"file '{os.path.abspath(clip)}'\n")

subprocess.run([
    "ffmpeg", "-y",
    "-f", "concat", "-safe", "0",
    "-i", "concat.txt",
    "-c", "copy",
    "output.mp4"
], check=True)

print("Done! output.mp4 ready.")
