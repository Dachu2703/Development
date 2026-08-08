import tempfile
from pathlib import Path

from auto_shorts import db


def test_db_create_and_project(tmp_path: Path):
    db_path = tmp_path / "test.db"
    db.init_db(str(db_path))
    pid = db.create_project(str(db_path), "testproj", "/tmp/video.mp4")
    assert isinstance(pid, int)
    proj = db.get_project(str(db_path), pid)
    assert proj and proj["name"] == "testproj"
