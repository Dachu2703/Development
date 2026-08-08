import json
import shutil
from pathlib import Path

import click

from . import transcribe, silence, scoring, align, export
from . import db, runner


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise click.ClickException("ffmpeg not found on PATH. Please install ffmpeg.")


@click.command()
@click.argument("input", type=click.Path(exists=True, dir_okay=False))
@click.option("--platform", default="YouTube Shorts", type=click.Choice(["YouTube Shorts", "Instagram Reels", "TikTok"]), help="Target platform for your short clips")
@click.option("--min-length", default=15, help="Minimum clip length (seconds)")
@click.option("--max-length", default=60, help="Maximum clip length (seconds)")
@click.option("--vertical", is_flag=True, help="Reframe to vertical 9:16 for Shorts" )
@click.option("--captions", is_flag=True, help="Burn captions into clips for Shorts")
@click.option("--cache-dir", default=None, help="Transcript cache directory")
@click.option("--output-dir", default="output", help="Output directory for clips")
@click.option("--dry-run", is_flag=True, help="Only create manifest, don't export clips")
def main(input, platform, min_length, max_length, vertical, captions, cache_dir, output_dir, dry_run):
    """auto-shorts: create YouTube Shorts-style vertical clips from a longer video.

    This is a scaffolded CLI that runs a minimal pipeline and writes a manifest.
    """
    _check_ffmpeg()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    click.echo("Transcribing (cached)...")
    transcript = transcribe.transcribe(input, cache_dir=cache_dir)
    click.echo(f"Transcript saved to {transcript}")
    click.echo("Detecting silences...")
    silences = silence.detect_silences(input)
    click.echo(f"Found {len(silences)} silence intervals")
    click.echo("Scoring candidate segments...")
    candidates = scoring.score_sentences(transcript, min_length=min_length, max_length=max_length)
    click.echo(f"Got {len(candidates)} candidate segments")
    click.echo("Aligning to silence boundaries and word boundaries...")
    aligned = align.snap_to_silence(candidates, silences, transcript_path=transcript, min_length=min_length, max_length=max_length)
    # validate no mid-word cuts
    try:
        from .scoring import ensure_no_midword
        ok = ensure_no_midword(aligned, transcript)
        if not ok:
            click.echo("Warning: some clip boundaries may cut mid-word. Consider increasing silence sensitivity or adjusting candidates.")
    except Exception:
        # scoring.ensure_no_midword may not be available
        pass
    manifest = {
        "source": input,
        "platform": platform,
        "segments": aligned,
    }
    manifest_path = Path(output_dir) / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    click.echo(f"Wrote manifest: {manifest_path}")
    if not dry_run:
        click.echo("Exporting clips...")
        exported = export.export_clips(input, aligned, output_dir, platform=platform, vertical=vertical, captions=captions)
        click.echo(f"Exported {len(exported)} clips to {output_dir}")


@click.group()
def cli():
    """auto-shorts project CLI."""


@cli.command()
@click.argument("name")
@click.argument("source", type=click.Path(exists=True, dir_okay=False))
@click.option("--db-path", "db_path", default="./auto_shorts.db", help="SQLite DB path")
def create_project(name, source, db_path):
    db.init_db(db_path)
    pid = db.create_project(db_path, name, source)
    click.echo(f"Created project {pid}")


@cli.command()
@click.option("--db-path", "db_path", default="./auto_shorts.db", help="SQLite DB path")
def list_projects(db_path):
    db.init_db(db_path)
    rows = db.list_projects(db_path)
    for r in rows:
        click.echo(f"{r['id']}: {r['name']} ({r['status']}) - {r['source']}")


@cli.command()
@click.argument("project_id", type=int)
@click.option("--db-path", "db_path", default="./auto_shorts.db", help="SQLite DB path")
@click.option("--output-dir", default="output", help="Output directory")
@click.option("--platform", default="YouTube Shorts", type=click.Choice(["YouTube Shorts", "Instagram Reels", "TikTok"]), help="Target platform for your short clips")
@click.option("--dry-run", is_flag=True)
@click.option("--clean-audio", is_flag=True)
@click.option("--vertical", is_flag=True)
@click.option("--captions", is_flag=True)
def run_project(project_id, db_path, output_dir, platform, dry_run, clean_audio, vertical, captions):
    db.init_db(db_path)
    proj = db.get_project(db_path, project_id)
    if not proj:
        click.echo("Project not found")
        return
    click.echo(f"Running project {project_id} (dry_run={dry_run}) for platform: {platform}...")
    manifest = runner.run_project(
        proj,
        db_path,
        output_dir,
        platform=platform,
        dry_run=dry_run,
        clean_audio=clean_audio,
        vertical=vertical,
        captions=captions,
    )
    click.echo(f"Manifest: {manifest}")


if __name__ == "__main__":
    cli()
