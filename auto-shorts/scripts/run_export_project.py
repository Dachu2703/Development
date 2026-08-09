import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_shorts import db, runner

DB = './auto_shorts.db'
PROJECT_ID = 26
OUTPUT = './output'
NUM_SHORTS = None

if __name__ == '__main__':
    db.init_db(DB)
    proj = db.get_project(DB, PROJECT_ID)
    if not proj:
        print('Project not found')
        sys.exit(1)
    try:
        manifest = runner.run_project(proj, DB, OUTPUT, dry_run=False, platform='YouTube Shorts', num_shorts=NUM_SHORTS)
        print('Export completed. Manifest:', manifest)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(2)
