import json
from pathlib import Path
import shutil
import tempfile
import streamlit as st

from auto_shorts import db, runner
from auto_shorts.logging_config import logger


st.set_page_config(page_title="auto-shorts Studio", layout="wide")
st.title("auto-shorts Studio")
st.subheader("Create vertical short clips from longer videos")

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
    "YouTube Shorts": {"min_length": 15, "max_length": 60, "num_shorts": 10},
    "Instagram Reels": {"min_length": 10, "max_length": 60, "num_shorts": 8},
    "TikTok": {"min_length": 10, "max_length": 60, "num_shorts": 12},
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
    min_length = st.number_input(
        "Min length (s)",
        min_value=5,
        max_value=300,
        value=settings["min_length"],
    )
with col3:
    max_length = st.number_input(
        "Max length (s)",
        min_value=10,
        max_value=600,
        value=settings["max_length"],
    )

remove_silence = st.checkbox("Trim silence from clips", value=True)
clean_audio_flag = st.checkbox("Noise reduction", value=False)
captions = st.checkbox("Burn captions into clips", value=False)
vertical = True
model_size = "small"
beam_size = 2
word_timestamps = captions

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

if st.button("Create dry-run manifest"):
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
            with st.spinner("Analyzing video and generating manifest…"):
                manifest_path = runner.run_project(
                    proj,
                    str(db_path),
                    str(output_base),
                    dry_run=True,
                    platform=platform,
                    min_length=min_length,
                    max_length=max_length,
                    clean_audio=clean_audio_flag,
                    vertical=vertical,
                    captions=captions,
                    model_size=model_size,
                    beam_size=beam_size,
                    word_timestamps=word_timestamps,
                )
            st.success(f"Manifest created: {manifest_path}")
            st.info("The manifest is a preview of the clip segments. No final clips are exported in dry-run mode.")
            with open(manifest_path, "r", encoding="utf-8") as mf:
                manifest = json.load(mf)
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
                        clean_audio=clean_audio_flag,
                        vertical=vertical,
                        captions=captions,
                        model_size=model_size,
                        beam_size=beam_size,
                        word_timestamps=word_timestamps,
                    )
                st.success(f"Export completed. Manifest: {manifest_path}")
            except Exception as e:
                logger.exception("Export failed during full job")
                st.error(f"Export failed: {e}")

