import json
import shutil
from pathlib import Path

import click

from . import transcribe, silence, scoring, align, export, transitions
from . import db, runner


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise click.ClickException("ffmpeg not found on PATH. Please install ffmpeg.")


@click.command()
@click.argument("input", type=click.Path(exists=True, dir_okay=False))
@click.option("--platform", default="YouTube Shorts", type=click.Choice(["YouTube Shorts", "Instagram Reels", "TikTok"]), help="Target platform for your short clips")
@click.option("--min-length", default=15, help="Minimum clip length (seconds)")
@click.option("--max-length", default=60, help="Maximum clip length (seconds)")
@click.option("--num-shorts", default=None, type=int, help="Number of shorts to generate (top-K candidates)")
@click.option("--prioritize-length", is_flag=True, help="Prioritize clip length over requested count (use max-length windows)")
@click.option("--force-exact-length", is_flag=True, help="Force exact clip length in seconds (no snapping)")
@click.option("--exact-clip-length", default=None, type=int, help="Exact clip length in seconds when forcing exact length")
@click.option("--vertical", is_flag=True, help="Reframe to vertical 9:16 for Shorts" )
@click.option("--captions", is_flag=True, help="Burn captions into clips for Shorts")
@click.option("--cache-dir", default=None, help="Transcript cache directory")
@click.option("--output-dir", default="output", help="Output directory for clips")
@click.option("--dry-run", is_flag=True, help="Only create manifest, don't export clips")
@click.option("--resolution", default="1080x1920", help="Output resolution as WxH (default: 1080x1920)")
@click.option("--guest-name", default=None, help="Guest name to overlay on short clips")
@click.option("--guest-contact", default=None, help="Guest contact number to overlay on short clips")
@click.option("--guest-extra", default=None, help="Extra guest information to overlay")
@click.option("--transitions", is_flag=True, help="Enable smooth camera transitions on main-content points")
@click.option("--transition-type", default="zoom_in", type=click.Choice(["zoom_in", "zoom_out", "fade_through"]), help="Transition effect type")
@click.option("--transition-duration", default=1.6, type=float, help="Transition duration in seconds")
@click.option("--transition-min-gap", default=6.0, type=float, help="Minimum seconds between transitions")
@click.option("--transition-threshold", default=3.0, type=float, help="Minimum content importance score to trigger a transition")
@click.option("--transition-max-per-clip", default=3, type=int, help="Maximum transitions per exported short clip")
def main(input, platform, min_length, max_length, vertical, captions, cache_dir, output_dir, dry_run, num_shorts, prioritize_length, force_exact_length, exact_clip_length, resolution, guest_name, guest_contact, guest_extra, transitions, transition_type, transition_duration, transition_min_gap, transition_threshold, transition_max_per_clip):
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
    top_k = int(num_shorts) if num_shorts else None
    candidates = scoring.score_sentences(transcript, min_length=min_length, max_length=max_length, top_k=top_k or 20, prioritize_length=bool(prioritize_length), force_exact_length=bool(force_exact_length), exact_clip_length=exact_clip_length)
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

    # Main-content transitions support
    transitions_config = None
    if transitions:
        click.echo("Marking main-content transition points...")
        with open(transcript, "r", encoding="utf-8") as tf:
            transcript_data = json.load(tf)
        transitions_config = {
            "enabled": True,
            "type": transition_type,
            "duration": transition_duration,
            "min_gap": transition_min_gap,
            "threshold": transition_threshold,
            "max_per_clip": transition_max_per_clip,
        }
        try:
            aligned = transitions.apply_transitions(aligned, transcript_data, transitions_config)
        except Exception as exc:
            click.echo(f"Warning: transitions skipped due to error: {exc}")

    # Guest info overlay configuration
    guest_info = None
    if guest_name or guest_contact:
        guest_info = {}
        if guest_name:
            guest_info["name"] = str(guest_name).strip()
        if guest_contact:
            guest_info["contact"] = str(guest_contact).strip()
        if guest_extra:
            guest_info["extra"] = str(guest_extra).strip()

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
        # honor num_shorts if provided via CLI (passed through runner)
        res_w, res_h = map(int, resolution.lower().split("x"))
        exported = export.export_clips(input, aligned, output_dir, platform=platform, vertical=vertical, captions=captions, resolution=(res_w, res_h), transitions=transitions_config, guest_info=guest_info)
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
@click.option("--num-shorts", default=None, type=int, help="Number of shorts to generate (top-K candidates)")
@click.option("--resolution", default="1080x1920", help="Output resolution as WxH (default: 1080x1920)")
@click.option("--guest-name", default=None, help="Guest name to overlay on short clips")
@click.option("--guest-contact", default=None, help="Guest contact number to overlay on short clips")
@click.option("--guest-extra", default=None, help="Extra guest information to overlay")
@click.option("--transitions", is_flag=True, help="Enable camera transitions on main-content points")
@click.option("--transition-type", default="zoom_in", type=click.Choice(["zoom_in", "zoom_out", "fade_through"]), help="Transition effect type")
@click.option("--transition-duration", default=1.6, type=float, help="Transition duration in seconds")
@click.option("--transition-min-gap", default=6.0, type=float, help="Minimum seconds between transitions")
@click.option("--transition-threshold", default=3.0, type=float, help="Minimum content importance score to trigger a transition")
@click.option("--transition-max-per-clip", default=3, type=int, help="Max transitions per exported short clip")
def run_project(project_id, db_path, output_dir, platform, dry_run, clean_audio, vertical, captions, num_shorts, resolution, guest_name, guest_contact, guest_extra, transitions, transition_type, transition_duration, transition_min_gap, transition_threshold, transition_max_per_clip):
    db.init_db(db_path)
    proj = db.get_project(db_path, project_id)
    if not proj:
        click.echo("Project not found")
        return
    click.echo(f"Running project {project_id} (dry_run={dry_run}) for platform: {platform}...")
    res_w, res_h = map(int, resolution.lower().split("x"))
    manifest = runner.run_project(
        proj,
        db_path,
        output_dir,
        platform=platform,
        dry_run=dry_run,
        num_shorts=num_shorts,
        clean_audio=clean_audio,
        vertical=vertical,
        captions=captions,
        resolution=(res_w, res_h),
        transitions_enabled=transitions,
        transitions_type=transition_type,
        transitions_duration=transition_duration,
        transitions_min_gap=transition_min_gap,
        transitions_threshold=transition_threshold,
        transitions_max_per_clip=transition_max_per_clip,
        guest_info={"name": guest_name, "contact": guest_contact, "extra": guest_extra} if (guest_name or guest_contact) else None,
    )
    click.echo(f"Manifest: {manifest}")


# The README quickstart (``python -m auto_shorts.cli input.mp4 ...``) passes a
# video path directly to the standalone ``main`` command. Project commands
# (create-project/list-projects/run-project) are dispatched to the ``cli``
# group. Route by the presence of a media file as the first argument.
if __name__ == "__main__":
    import sys
    _MEDIA_SUFFIXES = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mpg", ".mpeg")
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(_MEDIA_SUFFIXES):
        main()
    else:
        cli()