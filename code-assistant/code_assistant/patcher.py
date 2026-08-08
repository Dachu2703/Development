import difflib
from pathlib import Path
from typing import Optional


def make_patch(file_path: str, new_text: str) -> str:
    """Return a unified diff patch between existing file and new_text."""
    p = Path(file_path)
    old = []
    if p.exists():
        old = p.read_text(encoding='utf-8').splitlines()
    new = new_text.splitlines()
    diff = difflib.unified_diff(old, new, fromfile=str(p), tofile=str(p), lineterm="")
    return "\n".join(diff)


def apply_patch_local(file_path: str, new_text: str, overwrite: bool = False) -> bool:
    """Write new_text to file_path. If file exists and overwrite=False, raises.

    Returns True on success.
    """
    p = Path(file_path)
    if p.exists() and not overwrite:
        raise FileExistsError(f"{file_path} exists; set overwrite=True to replace")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_text, encoding='utf-8')
    return True
