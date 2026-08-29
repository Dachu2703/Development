import os
import shutil
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_shorts import db, runner
from auto_shorts.logging_config import logger

st.set_page_config(page_title="auto-shorts Studio", layout="wide")
st.title("auto-shorts Studio")
st.subheader("Create vertical short clips from longer videos")

platform = st.selectbox("Publish to", ["YouTube Shorts", "Instagram Reels", "TikTok"])
defaults = {"YouTube Shorts": (60, 10), "Instagram Reels": (60, 8), "TikTok": (60, 12)}
default_duration, default_count = defaults[platform]

col1, col2 = st.columns(2)
with col1:
    num_shorts = st.number_input("Number of clips", 1, 50, default_count)
with col2:
    target_duration = st.number_input("Clip length (seconds)", 15, 180, default_duration)

fine_tune_pauses = st.checkbox("Improve pause trimming (slower)")
clean_audio = st.checkbox("Clean background noise")
captions = st.checkbox("Add English captions (slower)")
fast_mode = st.checkbox("Use faster analysis", value=True)
resolution_text = st.selectbox("Output resolution", ["1080x1920", "1920x1080", "1080x1080"])
resolution = tuple(int(value) for value in resolution_text.split("x"))
model_size = "tiny" if fast_mode else "small"
beam_size = 1 if fast_mode else 2

uploaded = st.file_uploader("Upload video", type=["mp4", "mov", "mkv", "avi", "webm"])
local_path = st.text_input("Or use a local video path", placeholder="D:\\tmp\\video.mp4")

output_dir = Path("./output")
db_path = Path("./auto_shorts.db")
tmp_root = ROOT / ".auto_shorts_tmp"
tmp_root.mkdir(parents=True, exist_ok=True)
ffmpeg_path = shutil.which("ffmpeg")
if ffmpeg_path:
    os.environ["PATH"] = str(Path(ffmpeg_path).parent) + os.pathsep + os.environ.get("PATH", "")
else:
    st.warning("ffmpeg is not installed or not available on PATH.")

st.header("Final processing")
proceed_col, cancel_col = st.columns(2)
proceed = proceed_col.button("Proceed", type="primary", use_container_width=True)
cancel = cancel_col.button("Cancel", use_container_width=True)

if cancel:
    st.session_state.pop("last_project_id", None)
    st.info("Process cancelled.")

if proceed:
    if not ffmpeg_path:
        st.error("Cannot proceed because ffmpeg is not available.")
    elif uploaded is None and not local_path:
        st.error("Provide a video file or local path before proceeding.")
    else:
        temp_dir = None
        if uploaded is not None:
            temp_dir = Path(tempfile.mkdtemp(prefix="auto-shorts-", dir=str(tmp_root)))
            source_path = temp_dir / uploaded.name
            source_path.write_bytes(uploaded.getbuffer())
        else:
            source_path = Path(local_path)

        if not source_path.exists():
            st.error("Local path does not exist.")
        else:
            progress = st.progress(0, text="0% - Preparing final process")

            def report_progress(value: int, message: str) -> None:
                progress.progress(value, text=f"{value}% - {message}")

            try:
                db.init_db(str(db_path))
                project_id = db.create_project(str(db_path), source_path.stem, str(source_path))
                project = db.get_project(str(db_path), project_id)
                with st.spinner("Creating final clips..."):
                    manifest_path = runner.run_project(
                        project,
                        str(db_path),
                        str(output_dir),
                        dry_run=False,
                        platform=platform,
                        min_length=max(5, int(target_duration * 0.85)),
                        max_length=min(180, int(target_duration * 1.15)),
                        num_shorts=int(num_shorts),
                        target_duration=int(target_duration),
                        clean_audio=clean_audio,
                        vertical=True,
                        captions=captions,
                        model_size=model_size,
                        beam_size=beam_size,
                        word_timestamps=False,
                        progress_callback=report_progress,
                        use_silence_detection=fine_tune_pauses,
                        resolution=resolution,
                        transitions_enabled=False,
                        guest_info={},
                        template_config=None,
                    )
                progress.progress(100, text="100% - Final clips completed")
                st.success(f"Final clips completed. Output: {manifest_path}")
            except Exception as exc:
                logger.exception("Pipeline failed during final processing")
                st.error(f"Processing failed: {exc}")
            finally:
                if temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
