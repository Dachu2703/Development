# Contributing

Steps to develop and run locally:

1. Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
pip install -r requirements.txt
```

2. Run tests:
```bash
pytest -q
```

3. Run the Streamlit UI for the studio:
```bash
streamlit run -m auto_shorts.streamlit_app
```

4. Use the CLI to create and run projects:
```bash
python -m auto_shorts.cli create-project "Episode 1" /path/to/video.mp4
python -m auto_shorts.cli run-project 1 --db-path ./auto_shorts.db --dry-run
```

Coding style: follow existing project conventions.
