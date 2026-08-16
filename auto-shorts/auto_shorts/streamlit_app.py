import json
import os
from pathlib import Path
import shutil
import tempfile
import streamlit as st

from auto_shorts import db, export, runner
from auto_shorts.logging_config import logger


st.set_page_config(page_title="auto-shorts Studio", layout="wide")
st.title("auto-shorts Studio")
st.subheader("Create vertical short clips from longer videos")

if "last_project_id" not in st.session_state:
    st.session_state["last_project_id"] = None
    st.session_state["last_manifest_path"] = None

st.markdown(
    "Use the upload or local path input, choose your platform, then run a dry-run to preview segments before exporting final clips."
)

platform = st.selectbox(
    "Target platform",
    ["YouTube Shorts", "Instagram Reels", "TikTok"],
    index=0,
)

platform_caption = {
    "YouTube Shorts": "Snappy vertical clips for YouTube.",
    "Instagram Reels": "Short, engaging Reels-ready clips.",
    "TikTok": "Fast-paced clips for TikTok.",
}
st.caption(platform_caption.get(platform, "Create vertical clips for social video platforms."))

platform_defaults = {
    "YouTube Shorts": {"target_duration": 60, "num_shorts": 10},
    "Instagram Reels": {"target_duration": 60, "num_shorts": 8},
    "TikTok": {"target_duration": 60, "num_shorts": 12},
}
settings = platform_defaults.get(platform, platform_defaults["YouTube Shorts"])

col1, col2, col3 = st.columns(3)
with col1:
    num_shorts = st.number_input(
        "Number of clips",
        min_value=1,
        max_value=50,
        value=settings["num_shorts"],
    )
with col2:
    target_duration = st.number_input(
        "Target clip duration (seconds)",
        min_value=15,
        max_value=180,
        value=settings["target_duration"],
        help="Clips are built around high-engagement moments. The duration may vary slightly to keep natural sentence boundaries, but never exceeds 180 seconds.",
    )
with col3:
    min_length = max(5, int(target_duration * 0.85))
    max_length = min(180, max(int(target_duration), int(target_duration * 1.15)))
    st.metric("Natural duration range", f"{min_length}–{max_length}s")

fine_tune_pauses = st.checkbox(
    "Fine-tune clip boundaries using full-video silence detection (slow)",
    value=False,
    help="Off uses transcript sentence boundaries for a fast preview. Enable only when you need additional pause-level trimming.",
)
clean_audio_flag = st.checkbox("Noise reduction", value=False)
captions = st.checkbox("Burn English captions into clips (slower)", value=False)
fast_mode = st.checkbox(
    "Faster processing (smaller model, quicker preview)",
    value=True,
    help="Use a faster transcription mode so the app runs faster on local machines.",
)
vertical = True
model_size = "tiny" if fast_mode else "small"
beam_size = 1 if fast_mode else 2
# A preview needs segment-level timestamps only. Word timestamps are expensive
# and are requested only by a full captioned export.
word_timestamps = False

if captions and fast_mode:
    st.info("Captions slow processing down. Disable captions to make export faster.")

st.header("Upload or select your video")
uploaded = st.file_uploader("Upload a video file", type=["mp4", "mov", "mkv", "avi", "webm"])
local_path = st.text_input("Or use a local file path", placeholder="D:\\tmp\\Amitsha.mp4")

st.markdown("**Output folder**")
st.info("`./output/project_<id>/<platform>/`", icon="ℹ️")

output_base = Path("./output")
db_path = Path("./auto_shorts.db")
project_tmp_root = Path(__file__).resolve().parents[1] / ".auto_shorts_tmp"
project_tmp_root.mkdir(parents=True, exist_ok=True)

def _create_upload_tempdir() -> Path:
    try:
        return Path(tempfile.mkdtemp(prefix="auto-shorts-", dir=str(project_tmp_root)))
    except Exception:
        return Path(tempfile.mkdtemp(prefix="auto-shorts-"))


def _find_ffmpeg_executable() -> Path | None:
    # First try normal PATH lookup
    exe_path = shutil.which("ffmpeg")
    if exe_path:
        return Path(exe_path)

    # Search WinGet's local package cache if ffmpeg is installed there
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        winget_base = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_base.exists():
            for candidate in winget_base.rglob("ffmpeg.exe"):
                return candidate

    # Search common manual install directories
    common_dirs = [
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
        Path("C:/Program Files (x86)/ffmpeg/bin"),
    ]
    for candidate in common_dirs:
        if candidate.exists():
            path = candidate / "ffmpeg.exe"
            if path.exists():
                return path

    return None


ffmpeg_exe = _find_ffmpeg_executable()
if ffmpeg_exe is not None:
    os.environ["PATH"] = str(ffmpeg_exe.parent) + os.pathsep + os.environ.get("PATH", "")
ffmpeg_available = ffmpeg_exe is not None
if not ffmpeg_available:
    st.warning(
        "ffmpeg is not installed or not available on PATH. Install ffmpeg to run the pipeline."
    )
    st.markdown(
        "Download and install ffmpeg from https://ffmpeg.org/download.html and add it to your PATH."
    )
else:
    st.info(f"Detected ffmpeg at: {ffmpeg_exe}")

if st.button("Create dry-run manifest"):
    if not ffmpeg_available:
        st.error("Cannot run dry-run because ffmpeg is not installed or not on PATH.")
    else:
        # determine source path
        if uploaded is None and not local_path:
            st.error("Provide a file via upload or local path")
        else:
            if uploaded is not None:
                tmpdir = _create_upload_tempdir()
                src_path = tmpdir / uploaded.name
                with open(src_path, "wb") as f:
                    f.write(uploaded.getbuffer())
            else:
                src_path = Path(local_path)
                if not src_path.exists():
                    st.error("Local path does not exist")
                    st.stop()

        st.info(f"Creating project for {src_path}")
        db.init_db(str(db_path))
        # The db.create_project signature is (db_path, name, source). We'll set name to filename
        proj_name = src_path.stem
        pid = db.create_project(str(db_path), proj_name, str(src_path))
        st.success(f"Project created: {pid}")

        proj = db.get_project(str(db_path), pid)
        st.info("Running pipeline (dry-run)... this may take a while")
        try:
            progress_bar = st.progress(0, text="Preparing analysis…")

            def update_progress(value: int, message: str) -> None:
                progress_bar.progress(value, text=message)

            with st.spinner("Analyzing video and generating manifest…"):
                manifest_path = runner.run_project(
                    proj,
                    str(db_path),
                    str(output_base),
                    dry_run=True,
                    platform=platform,
                    min_length=min_length,
                    max_length=max_length,
                    num_shorts=int(num_shorts),
                    target_duration=int(target_duration),
                    clean_audio=clean_audio_flag,
                    vertical=vertical,
                    captions=captions,
                    model_size=model_size,
                    beam_size=beam_size,
                    word_timestamps=word_timestamps,
                    progress_callback=update_progress,
                    use_silence_detection=fine_tune_pauses,
                )
            st.success(f"Manifest created: {manifest_path}")
            st.session_state["last_project_id"] = pid
            st.session_state["last_manifest_path"] = str(manifest_path)
            with open(manifest_path, "r", encoding="utf-8") as mf:
                manifest = json.load(mf)
            st.session_state["last_manifest_segments"] = manifest.get("segments", [])
            st.info("The manifest is a preview of the clip segments. No final clips are exported in dry-run mode.")
            st.write("Detected segments:")
            for i, seg in enumerate(manifest.get("segments", []), start=1):
                st.markdown(f"**Clip {i}** — {seg.get('start'):.2f}s to {seg.get('end'):.2f}s — {seg.get('reason','')}")

            # generate waveform/timeline from source audio
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(str(src_path))
                # create RMS per 100ms
                window_ms = 100
                values = []
                for ms in range(0, len(audio), window_ms):
                    chunk = audio[ms: ms + window_ms]
                    values.append(chunk.rms)
                st.subheader("Waveform (RMS) — timeline overview")
                st.line_chart(values)
                # overlay segment markers as text list
                st.write("Segments:")
                for i, seg in enumerate(manifest.get("segments", []), start=1):
                    st.write(f"{i}: {seg.get('start'):.1f}s - {seg.get('end'):.1f}s")
            except Exception:
                st.info("Waveform preview unavailable (install pydub/soundfile).")
        except Exception as e:
            logger.exception("Pipeline failed during dry-run")
            st.error(f"Pipeline failed: {e}")

        # cleanup uploaded tmp files only
        if uploaded is not None:
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

if st.session_state.get("last_project_id"):
    st.markdown("---")
    st.subheader("Dry-run completed — ready to export")
    manifest_segments = st.session_state.get("last_manifest_segments", [])
    st.write(f"Project ID: {st.session_state['last_project_id']}")
    st.write(f"Detected segments: {len(manifest_segments)}")
    st.write(f"Manifest: {st.session_state['last_manifest_path']}")
    export_path = output_base / f"project_{st.session_state['last_project_id']}" / platform.replace(" ", "_")
    st.write(f"Export folder: `{export_path}`")
    if st.button("Export clips for last dry-run"):
        proj = db.get_project(str(db_path), int(st.session_state["last_project_id"]))
        try:
            if captions:
                # The preview intentionally skips word timestamps. Captioned
                # output therefore needs one full pass to obtain them.
                st.info("Captions need word timestamps, so this export will run one additional transcription pass.")
                with st.spinner("Exporting captioned clips…"):
                    manifest_path = runner.run_project(
                        proj, str(db_path), str(output_base), dry_run=False,
                        platform=platform, min_length=min_length, max_length=max_length,
                        num_shorts=int(num_shorts), target_duration=int(target_duration),
                        clean_audio=clean_audio_flag, vertical=vertical, captions=True,
                        model_size=model_size, beam_size=beam_size, word_timestamps=True,
                        use_silence_detection=fine_tune_pauses,
                    )
                st.success(f"Export completed. Manifest: {manifest_path}")
            else:
                # Reuse the already-scored manifest: no transcription, silence
                # scan, or peak-selection work is repeated during export.
                with st.spinner("Exporting saved clip selections…"):
                    results = export.export_clips(
                        proj["source"], manifest_segments, str(export_path), platform=platform,
                        vertical=vertical, captions=False, clean_audio_flag=clean_audio_flag,
                    )
                for result, segment in zip(results, manifest_segments):
                    db.add_clip(
                        str(db_path), proj["id"], result["start"], result["end"], result["file"],
                        float(segment.get("score", 0.0)), segment.get("reason", ""),
                    )
                db.update_project_status(str(db_path), proj["id"], "completed")
                st.success(f"Export completed: {len(results)} clips")
            st.write(f"Final clips will be written to `{export_path}`")
        except Exception as e:
            logger.exception("Export failed during last-dry-run export")
            st.error(f"Export failed: {e}")

if st.button("Export Clips (run full job)"):
    st.info("This will run the full export (may be slow). Ensure project exists via dry-run first.")
    # list projects and let user pick
    db.init_db(str(db_path))
    rows = db.list_projects(str(db_path))
    if not rows:
        st.warning("No projects found. Create a project first.")
    else:
        opts = {r['id']: f"{r['id']}: {r['name']} ({r['status']})" for r in rows}
        sel = st.selectbox("Select project to run", list(opts.keys()), format_func=lambda x: opts[x])
        if st.button("Confirm Export"):
            proj = db.get_project(str(db_path), int(sel))
            try:
                with st.spinner("Exporting final clips… this may take several minutes"):
                    manifest_path = runner.run_project(
                        proj,
                        str(db_path),
                        str(output_base),
                        dry_run=False,
                        platform=platform,
                        min_length=min_length,
                            max_length=max_length,
                            num_shorts=int(num_shorts),
                            target_duration=int(target_duration),
                        clean_audio=clean_audio_flag,
                        vertical=vertical,
                        captions=captions,
                        model_size=model_size,
                        beam_size=beam_size,
                        word_timestamps=word_timestamps,
                        use_silence_detection=fine_tune_pauses,
                    )
                st.success(f"Export completed. Manifest: {manifest_path}")
            except Exception as e:
                logger.exception("Export failed during full job")
                st.error(f"Export failed: {e}")

