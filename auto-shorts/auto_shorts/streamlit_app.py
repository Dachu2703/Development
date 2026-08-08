import json
from pathlib import Path
import shutil
import tempfile
import streamlit as st

from auto_shorts import db, runner


st.set_page_config(page_title="auto-shorts Studio", layout="wide")
st.title("auto-shorts Studio — Smart Short Clip Maker")
st.markdown(
    "Create platform-ready vertical clips from longer videos with clear split guidance, clean cuts, and optional captions."
)

st.sidebar.title("Export settings")
platform = st.sidebar.selectbox(
    "Target platform",
    ["YouTube Shorts", "Instagram Reels", "TikTok"],
    index=0,
)

platform_caption = {
    "YouTube Shorts": "Generate snappy vertical cuts optimized for YouTube Shorts.",
    "Instagram Reels": "Create engaging short reels for Instagram with the right pacing.",
    "TikTok": "Produce fast, vertical TikTok-ready clips with attention-grabbing timing.",
}
st.caption(platform_caption.get(platform, "Create vertical clips for social video platforms."))

st.info(
    "**How it works:**\n"
    "1. Upload a video file or paste a local file path.\n"
    "2. Pick the target platform and set clip length.\n"
    "3. Click `Create Project & Generate (dry-run manifest)` to preview segments.\n"
    "4. Then click `Export Clips (run full job)` to create final shorts."
)

platform_defaults = {
    "YouTube Shorts": {"min_length": 15, "max_length": 60, "num_shorts": 10},
    "Instagram Reels": {"min_length": 10, "max_length": 60, "num_shorts": 8},
    "TikTok": {"min_length": 10, "max_length": 60, "num_shorts": 12},
}
settings = platform_defaults.get(platform, platform_defaults["YouTube Shorts"])

st.sidebar.header(f"{platform} Settings")
st.sidebar.markdown(
    "**Recommended settings:**\n"
    f"- Clip length: {settings['min_length']} to {settings['max_length']} seconds\n"
    f"- Suggested clips: {settings['num_shorts']}"
)
st.sidebar.info("For very large videos (>1 GB), prefer the local file path input instead of browser upload.")
num_shorts = st.sidebar.number_input(
    "Number of clips",
    min_value=1,
    max_value=50,
    value=settings["num_shorts"],
)
min_length = st.sidebar.number_input(
    "Min length (s)",
    min_value=5,
    max_value=300,
    value=settings["min_length"],
)
max_length = st.sidebar.number_input(
    "Max length (s)",
    min_value=10,
    max_value=600,
    value=settings["max_length"],
)
remove_silence = st.sidebar.checkbox("Remove silence", value=True)
clean_audio_flag = st.sidebar.checkbox("Noise reduction", value=False)
vertical = True
st.sidebar.info("Vertical 9:16 output is always applied for short-form platforms.")
captions = st.sidebar.checkbox("Burn captions", value=False)


st.header("Upload video")
uploaded = st.file_uploader("Drop a video file or browse", type=["mp4", "mov", "mkv", "avi", "webm"])
local_path = st.text_input("Or paste local file path")

output_base = Path("./output")
db_path = Path("./auto_shorts.db")

st.markdown("#### Output folder")
st.write("Final clips and manifest files are saved to: `./output/project_<id>/<platform>/` inside the app folder.")
st.write("For example, if project id is 1 and platform is YouTube Shorts, output goes to `./output/project_1/YouTube_Shorts/`.")

if st.button("Create Project & Generate (dry-run manifest)"):
    # determine source path
    if uploaded is None and not local_path:
        st.error("Provide a file via upload or local path")
    else:
        if uploaded is not None:
            tmpdir = Path(tempfile.mkdtemp(prefix="auto-shorts-"))
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
                )
                st.success(f"Export completed. Manifest: {manifest_path}")
            except Exception as e:
                st.error(f"Export failed: {e}")

