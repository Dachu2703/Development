# Code Assistant (local)

Simple local Code Assistant to search the workspace, preview edits, and apply patches.

Run:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run -m code_assistant.app
```

Notes:
- LLM integration uses `OPENAI_API_KEY` if set.
- Patches require explicit confirmation before applying.
