# auto-shorts

auto-shorts is a CLI tool to split longer videos into short vertical clips suitable for YouTube Shorts, Instagram Reels, and TikTok.

This repository contains a scaffolded implementation with core modules and a basic CLI. The current code provides the pipeline wiring and simple stubs for transcription/scoring; replace the stubs with real whisper/faster-whisper logic for full functionality.

Requirements
- Python 3.11+
- ffmpeg installed and on PATH

Quickstart

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run (dry-run manifest only):

```bash
python -m auto_shorts.cli input.mp4 --platform "YouTube Shorts" --dry-run
```

Platform-specific export example:

```bash
python -m auto_shorts.cli input.mp4 --platform "Instagram Reels" --min-length 10 --max-length 30 --vertical --captions
```

Project flow (SQLite DB):

```bash
# create a project
python -m auto_shorts.cli create-project "Episode 1" /path/to/input.mp4

# list projects
python -m auto_shorts.cli list-projects

# run project (dry-run)
python -m auto_shorts.cli run-project 1 --platform "YouTube Shorts" --dry-run

# run project and export clips
python -m auto_shorts.cli run-project 1 --platform "YouTube Shorts" --clean-audio --vertical --captions
```

Streamlit UI (preview manifest):

```bash
streamlit run -m auto_shorts.streamlit_app
```

Run tests:

```bash
pytest auto-shorts/tests -q
```

Examples:

```powershell
.\auto-shorts\examples\run_example.ps1
```

Next steps
- Implement real transcription in `auto_shorts/transcribe.py` using `faster-whisper`.
- Improve silence detection, scoring heuristics, and add optional LLM scoring.
- Implement vertical reframing and captions in `export.py`.
