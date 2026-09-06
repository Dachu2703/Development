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

st.markdown(
    """
    <div style="background:#111827;border:1px solid #374151;border-radius:12px;padding:12px 16px;margin-bottom:16px;">
      <div style="font-size:14px;font-weight:600;color:#F9FAFB;">Simple 3-section layout</div>
      <div style="font-size:13px;color:#D1D5DB;">55% video • 15% title • 30% image</div>
    </div>
    """,
    unsafe_allow_html=True,
)

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

col_padding1, col_padding2 = st.columns(2)
with col_padding1:
    add_video_padding = st.checkbox("Add padding around video (smaller frame)", value=True)
with col_padding2:
    st.caption("Leave unchecked to stretch video to fill frame")

col_fast1, col_fast2, col_fast3 = st.columns(3)
with col_fast1:
    fast_mode = st.checkbox("Use faster analysis", value=True)
with col_fast2:
    ultra_fast_mode = st.checkbox("Ultra-fast export", value=False)
with col_fast3:
    lightning_mode = st.checkbox("⚡ Lightning-fast (fastest)", value=False)

# In lightning mode, disable slow features
if lightning_mode:
    fine_tune_pauses = False
    clean_audio = False
    captions = False
    ultra_fast_mode = True

resolution_text = st.selectbox("Output resolution", ["1080x1920", "1920x1080", "1080x1080"])
resolution = tuple(int(value) for value in resolution_text.split("x"))

# Reduce resolution in lightning mode for more speed
if lightning_mode:
    resolution = (720, 1280)  # 33% faster encoding than 1080x1920

# Set model based on speed preference
if lightning_mode:
    model_size = "tiny"
    beam_size = 1
    ultra_fast_mode = True  # Force ultrafast export
    fine_tune_pauses = False  # Disable pause tuning
elif fast_mode:
    model_size = "tiny"
    beam_size = 1
else:
    model_size = "small"
    beam_size = 2

uploaded = st.file_uploader("Source video", type=["mp4", "mov", "mkv", "avi", "webm"])
local_path = st.text_input("Or use a local video path", placeholder="D:\\tmp\\video.mp4")
frame_layout = st.radio("Frame Layout", ["Full Size Short Video", "3-Part Frame"], index=0, horizontal=True)
show_three_part = frame_layout == "3-Part Frame"
short_title = st.text_input("Short video title", placeholder="Enter title for the middle section") if show_three_part else ""
bottom_image = st.file_uploader("Bottom image", type=["png", "jpg", "jpeg", "webp"]) if show_three_part else None

if show_three_part:
    st.markdown(
        """
        <div style="margin:12px 0 18px 0; border:1px solid #374151; border-radius:10px; overflow:hidden; background:#0B1220;">
          <div style="display:flex; flex-direction:column; width:100%; font-family:Arial, sans-serif;">
            <div style="height:55px; background:#1F2937; color:#F9FAFB; display:flex; align-items:center; justify-content:center; font-size:13px;">VIDEO 55%</div>
            <div style="height:15px; background:#374151; color:#F9FAFB; display:flex; align-items:center; justify-content:center; font-size:11px;">TITLE 15%</div>
            <div style="height:30px; background:#111827; color:#F9FAFB; display:flex; align-items:center; justify-content:center; font-size:12px;">IMAGE 30%</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("Full Size Short Video mode keeps the full guest video on one single 1080x1920 canvas with no top, middle, or bottom split.")

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
        bottom_image_path = None
        if uploaded is not None:
            temp_dir = Path(tempfile.mkdtemp(prefix="auto-shorts-", dir=str(tmp_root)))
            source_path = temp_dir / uploaded.name
            source_path.write_bytes(uploaded.getbuffer())
        else:
            source_path = Path(local_path)

        if bottom_image is not None:
            if temp_dir is None:
                temp_dir = Path(tempfile.mkdtemp(prefix="auto-shorts-", dir=str(tmp_root)))
            bottom_image_path = temp_dir / bottom_image.name
            bottom_image_path.write_bytes(bottom_image.getbuffer())

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
                    guest_info = {
                        "title": short_title.strip() if show_three_part and short_title else "",
                        "name": "",
                        "contact": "",
                    }
                    template_config = {
                        "enabled": show_three_part,
                        "title": short_title.strip() if show_three_part and short_title else "",
                        "top_height": 0,
                        "subscribe_height": 0,
                        "video_height": int(round(resolution[1] * 0.55)),
                        "title_height": int(round(resolution[1] * 0.15)),
                        "bottom_background": "black",
                    }
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
                        guest_info=guest_info,
                        template_config=template_config,
                        bottom_image_path=str(bottom_image_path) if show_three_part and bottom_image_path else None,
                        fast_export=ultra_fast_mode,
                        lightning_mode=lightning_mode,
                        add_padding=add_video_padding,
                        frame_layout=frame_layout,
                    )
                progress.progress(100, text="100% - Final clips completed")
                st.success(f"Final clips completed. Output: {manifest_path}")
            except runner.RequestedClipCountError as exc:
                logger.warning("Fewer clips were generated than requested: %s", exc)
                progress.progress(100, text="100% - Partial results completed")
                st.warning(
                    "The video processing completed, but fewer clips were available "
                    "than requested. The generated clips were saved."
                )
                st.info(str(exc))
            except Exception as exc:
                logger.exception("Pipeline failed during final processing")
                st.error(f"Processing failed: {exc}")
            finally:
                if temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
