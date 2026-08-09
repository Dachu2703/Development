from auto_shorts import runner

proj = {"id":999, "source": "D:/tmp/Amitsha.mp4", "name":"Amitsha"}
try:
    runner.run_project(proj, "./auto_shorts.db", "./output", dry_run=True, model_size="tiny", beam_size=1, word_timestamps=False, num_shorts=None)
except Exception:
    import traceback, sys
    traceback.print_exc()
    sys.exit(1)
print("Completed without exception")
