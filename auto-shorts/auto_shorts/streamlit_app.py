import os
import shutil
import sys
import tempfile
import hashlib
import inspect
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_shorts import db, runner
from auto_shorts.logging_config import logger

st.set_page_config(page_title="auto-shorts Studio", page_icon="🎬", layout="wide")

# ---------- Header ----------
st.title("🎬 auto-shorts Studio")
st.caption("Create professional vertical clips • Configure design • Preview • Confirm • Generate")

st.markdown(
    """
    <div style="padding:14px 18px;border:1px solid #374151;border-radius:14px;
                margin:8px 0 18px 0;">
      <b>Two output layouts</b><br>
      <span style="font-size:13px;">
      Full Size: centered guest + full-screen blurred background + optional bottom image/title •
      3-Part: 65% video • 10% title • 25% image
      </span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------- Step 1 ----------
with st.expander("1. Video & Content", expanded=True):
    a, b = st.columns([1, 1])
    with a:
        uploaded = st.file_uploader(
            "Source video",
            type=["mp4", "mov", "mkv", "avi", "webm"],
            help="Upload the long source video.",
        )
    with b:
        local_path = st.text_input(
            "Or use a local video path",
            placeholder=r"D:\tmp\video.mp4",
        )

    a, b, c, d = st.columns(4)
    with a:
        platform = st.selectbox(
            "Publish to",
            ["YouTube Shorts", "Instagram Reels", "Facebook Reels", "TikTok"],
        )
    defaults = {
        "YouTube Shorts": (60, 10),
        "Instagram Reels": (60, 8),
        "Facebook Reels": (60, 8),
        "TikTok": (60, 12),
    }
    default_duration, default_count = defaults[platform]
    with b:
        num_shorts = st.number_input("Number of clips", 1, 50, default_count)
    with c:
        target_duration = st.number_input(
            "Clip length (seconds)", 15, 180, default_duration
        )
    with d:
        resolution_text = st.selectbox(
            "Output resolution",
            ["1080x1920", "720x1280", "1920x1080", "1080x1080"],
        )

resolution = tuple(int(x) for x in resolution_text.split("x"))

# ---------- Step 2 ----------
with st.expander("2. Design Configuration", expanded=True):
    frame_layout = st.radio(
        "Choose output design",
        ["Full Size Short Video", "3-Part Frame"],
        horizontal=True,
    )

    if frame_layout == "Full Size Short Video":
        st.info(
            "Full Size: full-screen blurred background with the original guest video "
            "centered on top. Your optional image and title are used as a bottom banner."
        )
    else:
        st.info("3-Part Frame: VIDEO 65% • TITLE 10% • IMAGE 25%")

    left, right = st.columns([1.1, 0.9])
    with left:
        short_title = st.text_input(
            "Title",
            placeholder="Enter title for the selected design",
            key="short_title",
        )
    with right:
        bottom_image = st.file_uploader(
            "Image / Bottom Design",
            type=["png", "jpg", "jpeg", "webp"],
            key="bottom_image",
        )
        if bottom_image is not None:
            st.image(bottom_image, caption="Current image preview", use_container_width=True)
            if st.button("Remove uploaded image", key="remove_bottom_image"):
                st.session_state.pop("bottom_image", None)
                st.rerun()

# ---------- Step 3 ----------
with st.expander("3. Branding", expanded=True):
    logo_col, watermark_col = st.columns(2)

    with logo_col:
        st.markdown("#### Logo")
        logo_enabled = st.toggle("Enable logo", value=False, key="logo_enabled")
        logo = None
        if logo_enabled:
            logo = st.file_uploader(
                "Upload logo (top-right)",
                type=["png", "jpg", "jpeg", "webp"],
                key="logo_file",
            )
            if logo is not None:
                st.image(logo, caption="Logo preview", width=150)
                if st.button("Remove logo", key="remove_logo"):
                    st.session_state.pop("logo_file", None)
                    st.rerun()

    with watermark_col:
        st.markdown("#### Watermark Name")
        watermark_enabled = st.toggle(
            "Enable watermark", value=False, key="watermark_enabled"
        )
        watermark_text = ""
        watermark_position = "Bottom Right"
        watermark_opacity = 0.35
        watermark_softness = 2

        if watermark_enabled:
            watermark_text = st.text_input(
                "Watermark name",
                placeholder="Enter channel name",
                key="watermark_text",
            )
            x, y = st.columns(2)
            with x:
                watermark_position = st.selectbox(
                    "Position",
                    ["Bottom Right", "Bottom Left", "Top Right", "Top Left", "Center"],
                    key="watermark_position",
                )
            with y:
                watermark_opacity = st.slider(
                    "Opacity", 0.05, 0.80, 0.35, 0.05, key="watermark_opacity"
                )
            watermark_softness = st.slider(
                "Softness", 0, 10, 2, key="watermark_softness"
            )

# ---------- Step 4 ----------
with st.expander("4. Processing Options", expanded=False):
    a, b, c = st.columns(3)
    with a:
        fine_tune_pauses = st.checkbox("Improve pause trimming (slower)")
    with b:
        clean_audio = st.checkbox("Clean background noise")
    with c:
        captions = st.checkbox("Add English captions (slower)")

    a, b, c = st.columns(3)
    with a:
        add_video_padding = st.checkbox(
            "Keep full video visible", value=True,
            help="Recommended to avoid cropping the guest in the 3-Part layout.",
        )
    with b:
        fast_mode = st.checkbox("Use faster analysis", value=True)
    with c:
        ultra_fast_mode = st.checkbox("Ultra-fast export", value=False)

    lightning_mode = st.checkbox("⚡ Lightning-fast export")
    if lightning_mode:
        resolution = (720, 1280)
        fine_tune_pauses = False
        clean_audio = False
        captions = False
        ultra_fast_mode = True

model_size = "tiny" if (fast_mode or lightning_mode) else "small"
beam_size = 1 if model_size == "tiny" else 2

# ---------- Preview approval ----------
cfg = repr(
    (
        uploaded.name if uploaded else "",
        local_path.strip(),
        platform,
        resolution,
        frame_layout,
        short_title.strip(),
        bottom_image.name if bottom_image else "",
        logo_enabled,
        logo.name if logo else "",
        watermark_enabled,
        watermark_text.strip(),
        watermark_position,
        watermark_opacity,
        watermark_softness,
    )
)
fingerprint = hashlib.sha256(cfg.encode("utf-8")).hexdigest()

st.subheader("5. Sample Preview")
st.caption(
    "Preview approval is required before final generation. If you change the design, "
    "title, image, logo or watermark, preview approval is automatically reset."
)

preview_col, status_col = st.columns([1, 1])
with preview_col:
    preview_clicked = st.button(
        "👁 Preview Sample Design",
        type="secondary",
        use_container_width=True,
    )

if preview_clicked:
    st.session_state["preview_fingerprint"] = fingerprint

approved = st.session_state.get("preview_fingerprint") == fingerprint
with status_col:
    if approved:
        st.success("Sample design approved. You can proceed with final generation.")
    else:
        st.warning("Preview approval required before final generation.")

if approved:
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown(f"**Layout:** {frame_layout}")
        st.markdown(f"**Title:** {short_title or 'Not set'}")
    with p2:
        st.markdown(f"**Logo:** {'Enabled' if logo_enabled and logo else 'Off'}")
        st.markdown(f"**Watermark:** {'Enabled' if watermark_enabled and watermark_text else 'Off'}")
    with p3:
        st.markdown(
            "**3-Part split:** VIDEO 65% / TITLE 10% / IMAGE 25%"
            if frame_layout == "3-Part Frame"
            else "**Full Size:** blurred background + centered guest"
        )

    if bottom_image is not None:
        st.image(
            bottom_image,
            caption=f"{frame_layout} image preview",
            width=420,
        )

# ---------- Final generation ----------
tmp_root = ROOT / ".auto_shorts_tmp"
tmp_root.mkdir(parents=True, exist_ok=True)
output_dir = Path("./output")
db_path = Path("./auto_shorts.db")

ffmpeg_path = shutil.which("ffmpeg")
if ffmpeg_path:
    os.environ["PATH"] = (
        str(Path(ffmpeg_path).parent)
        + os.pathsep
        + os.environ.get("PATH", "")
    )
else:
    st.warning("ffmpeg is not installed or not available on PATH.")

st.subheader("6. Final Confirmation")
proceed_col, cancel_col = st.columns(2)
proceed = proceed_col.button(
    "🚀 Proceed with Final Generation",
    type="primary",
    use_container_width=True,
    disabled=not approved,
)
cancel = cancel_col.button("Cancel", use_container_width=True)

if cancel:
    st.session_state.pop("preview_fingerprint", None)
    st.session_state.pop("last_project_id", None)
    st.info("Process cancelled.")

if proceed:
    progress = None
    temp_dir = None
    try:
        if not ffmpeg_path:
            raise RuntimeError("Cannot proceed because ffmpeg is not available.")
        if uploaded is None and not local_path.strip():
            raise ValueError("Provide a source video file or local path before proceeding.")

        temp_dir = Path(tempfile.mkdtemp(prefix="auto-shorts-", dir=str(tmp_root)))

        if uploaded is not None:
            source_path = temp_dir / uploaded.name
            source_path.write_bytes(uploaded.getbuffer())
        else:
            source_path = Path(local_path.strip())

        if not source_path.exists():
            raise FileNotFoundError(f"Source video does not exist: {source_path}")

        def save_upload(uploaded_file, prefix):
            if uploaded_file is None:
                return None
            target = temp_dir / f"{prefix}_{uploaded_file.name}"
            target.write_bytes(uploaded_file.getbuffer())
            return str(target)

        bottom_image_path = save_upload(bottom_image, "bottom")
        logo_path = save_upload(logo, "logo") if logo_enabled else None

        progress = st.progress(0, text="0% - Preparing final process")

        def report_progress(value: int, message: str) -> None:
            progress.progress(int(value), text=f"{int(value)}% - {message}")

        db.init_db(str(db_path))
        project_id = db.create_project(str(db_path), source_path.stem, str(source_path))
        project = db.get_project(str(db_path), project_id)

        template_config = {
            "enabled": frame_layout == "3-Part Frame",
            "title": short_title.strip(),
            "top_height": 0,
            "subscribe_height": 0,
            "video_height": int(round(resolution[1] * 0.65)),
            "title_height": int(round(resolution[1] * 0.10)),
            "bottom_background": "black",
        }

        kwargs = {
            "dry_run": False,
            "platform": platform,
            "min_length": max(5, int(target_duration * 0.85)),
            "max_length": min(180, int(target_duration * 1.15)),
            "num_shorts": int(num_shorts),
            "target_duration": int(target_duration),
            "clean_audio": clean_audio,
            "vertical": True,
            "captions": captions,
            "model_size": model_size,
            "beam_size": beam_size,
            "word_timestamps": False,
            "progress_callback": report_progress,
            "use_silence_detection": fine_tune_pauses,
            "resolution": resolution,
            "transitions_enabled": False,
            "guest_info": {"title": short_title.strip(), "name": "", "contact": ""},
            "template_config": template_config,
            "bottom_image_path": bottom_image_path,
            "fast_export": ultra_fast_mode,
            "lightning_mode": lightning_mode,
            "add_padding": add_video_padding,
            "frame_layout": frame_layout,
            "logo_path": logo_path,
            "watermark_text": watermark_text.strip(),
            "watermark_enabled": watermark_enabled,
            "watermark_position": watermark_position,
            "watermark_opacity": watermark_opacity,
            "watermark_softness": watermark_softness,
        }

        # run_project() accepts **kwargs, so preserve all design/branding
        # parameters instead of silently dropping them.
        signature = inspect.signature(runner.run_project)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_kwargs:
            run_kwargs = dict(kwargs)
        else:
            accepted = set(parameters)
            run_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in accepted
            }

        with st.spinner("Creating final clips..."):
            manifest_path = runner.run_project(
                project,
                str(db_path),
                str(output_dir),
                **run_kwargs,
            )

        progress.progress(100, text="100% - Final clips completed")
        st.success(f"Final clips completed. Output: {manifest_path}")

    except runner.RequestedClipCountError as exc:
        logger.warning("Fewer clips were generated than requested: %s", exc)
        if progress is not None:
            progress.progress(100, text="100% - Partial results completed")
        st.warning(str(exc))
    except Exception as exc:
        logger.exception("Pipeline failed during final processing")
        st.error(f"Processing failed: {exc}")
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
