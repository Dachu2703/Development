# Example PowerShell script to create a project and run a dry-run
$env:PATH += ";C:\ffmpeg\bin"  # ensure ffmpeg on PATH or already configured
python -m auto_shorts.cli create-project "Example" "C:\path\to\video.mp4" --db-path .\auto_shorts.db
python -m auto_shorts.cli run-project 1 --db-path .\auto_shorts.db --dry-run
