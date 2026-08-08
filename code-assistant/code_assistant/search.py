import os
import re
from typing import List, Dict


def search_code(query: str, root: str = ".", max_results: int = 100) -> List[Dict]:
    """Search for `query` (regex or plain) under `root` and return matches.

    Returns list of {file, line_no, line}.
    """
    results = []
    pattern = None
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        # treat as plain substring
        pattern = None

    for dirpath, dirnames, filenames in os.walk(root):
        # skip virtual envs and .git
        if any(p in dirpath for p in (".git", "venv", ".venv", "__pycache__")):
            continue
        for fn in filenames:
            if fn.endswith(('.pyc', '.exe', '.dll')):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    for i, line in enumerate(f, start=1):
                        hay = line.strip()
                        if pattern:
                            if pattern.search(hay):
                                results.append({'file': path, 'line_no': i, 'line': hay})
                        else:
                            if query.lower() in hay.lower():
                                results.append({'file': path, 'line_no': i, 'line': hay})
                        if len(results) >= max_results:
                            return results
            except Exception:
                continue
    return results
