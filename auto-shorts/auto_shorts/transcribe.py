import hashlib
import itertools
import json
import subprocess
from functools import lru_cache
from collections.abc import Iterator
from pathlib import Path
from typing import Dict, List

from .logging_config import logger


# Keep generated data inside the project by default.
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".auto_shorts_cache"


def _ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        r"default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return 0.0
    try:
        return float(out.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _cache_key_for(path: Path) -> str:
    st = path.stat()
    key_src = f"{path.resolve()}::{st.st_mtime_ns}::{st.st_size}"
    return hashlib.sha1(key_src.encode()).hexdigest()


@lru_cache(maxsize=2)
def _load_model(model_size: str):
    """Load each selected Whisper model once per application process."""
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError(
            "faster-whisper is required for transcription. "
            "Install with `pip install faster-whisper`."
        ) from exc

    compute_type = "int8"
    try:
        model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
        logger.debug(
            f"faster-whisper using compute_type={compute_type} "
            f"device=cpu model={model_size}"
        )
    except Exception as exc:
        compute_type = "default"
        logger.warning(
            f"faster-whisper compute_type={compute_type} failed, "
            f"falling back to default: {exc}"
        )
        model = WhisperModel(model_size, device="cpu")
        logger.debug(
            f"faster-whisper fallback to compute_type={compute_type} "
            f"device=cpu model={model_size}"
        )
    return model


def transcribe(
    video_path: str,
    cache_dir: str = None,
    model_size: str = "small",
    beam_size: int = 1,
    word_timestamps: bool = False,
    language: str = "en",
    task: str = "transcribe",
    skip_vad: bool = False,
) -> str:
    """Transcribe or translate a video with faster-whisper.

    Args:
        video_path: Path to video file.
        cache_dir: Cache directory for transcripts.
        model_size: Whisper model size (tiny, base, small, medium, large).
        beam_size: Beam size for decoding.
        word_timestamps: Include word-level timestamps.
        language: Source language code, e.g. ``ta`` for Tamil.
        task: ``transcribe`` keeps the source language; ``translate`` translates
            speech into English while preserving Whisper timestamps.
        skip_vad: Skip VAD filtering for faster processing.

    Returns:
        Path to the cached transcript JSON.
    """
    src = Path(video_path)
    if not src.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if cache_dir is None:
        cache_dir_path = DEFAULT_CACHE_DIR
    else:
        cache_dir_path = Path(cache_dir)
    cache_dir_path.mkdir(parents=True, exist_ok=True)

    language = str(language or "en").strip().lower()
    task = str(task or "transcribe").strip().lower()

    if task not in {"transcribe", "translate"}:
        raise ValueError("task must be 'transcribe' or 'translate'")

    # Language + task are part of the cache key. This prevents a Tamil source
    # transcript from being reused as an English translation, or vice versa.
    key = _cache_key_for(src)
    option_key = (
        f"model={model_size}|"
        f"beam={beam_size}|"
        f"timestamps={word_timestamps}|"
        f"language={language}|"
        f"task={task}|"
        f"vad={not skip_vad}"
    )
    option_hash = hashlib.sha1(option_key.encode()).hexdigest()
    out_path = (
        cache_dir_path
        / f"{src.stem}-{key}-{option_hash}.transcript.json"
    )

    if out_path.exists():
        return str(out_path)

    model = _load_model(model_size)
    segments = []
    words_all: List[Dict] = []

    logger.debug(
        f"transcribe starting model={model_size} beam_size={beam_size} "
        f"word_timestamps={word_timestamps} language={language} task={task}"
    )

    result = model.transcribe(
        str(src),
        beam_size=beam_size,
        word_timestamps=word_timestamps,
        language=language,
        task=task,
        vad_filter=not skip_vad,
    )
    logger.debug(f"transcribe result type={type(result)}")

    if isinstance(result, tuple) and len(result) == 2:
        segment_iter = result[0]
    else:
        segment_iter = result

    logger.debug(
        f"segment_iter type before normalization={type(segment_iter)} "
        f"isiterator={isinstance(segment_iter, Iterator)}"
    )

    if isinstance(segment_iter, Iterator) and not isinstance(
        segment_iter, (list, tuple, dict, str, bytes)
    ):
        try:
            first_item = next(segment_iter)
        except StopIteration:
            segment_iter = []
            first_item = None
        except Exception:
            logger.exception("Failed to consume first item of transcribe result")
            raise

        if first_item is None:
            segment_iter = []
        elif (
            isinstance(first_item, tuple)
            and len(first_item) == 2
            and isinstance(first_item[0], (list, tuple, Iterator))
        ):
            segment_iter = first_item[0]
            if isinstance(segment_iter, Iterator):
                segment_iter = itertools.chain(segment_iter)
        else:
            segment_iter = itertools.chain([first_item], segment_iter)

    for segment in segment_iter:
        if isinstance(segment, dict):
            start = segment.get("start")
            end = segment.get("end")
            text = segment.get("text", "")
            word_items = segment.get("words", [])
        else:
            start = getattr(segment, "start", None)
            end = getattr(segment, "end", None)
            text = getattr(segment, "text", "")
            word_items = getattr(segment, "words", [])

        if not word_timestamps:
            word_items = []
        elif word_items is None or isinstance(word_items, (str, bytes, dict)):
            word_items = []
        elif not isinstance(word_items, list):
            try:
                word_items = list(word_items)
            except Exception:
                logger.exception(
                    "Failed converting word_items to list; normalizing to []"
                )
                word_items = []

        seg = {
            "start": float(start or 0.0),
            "end": float(end or 0.0),
            "text": str(text or "").strip(),
            "words": [],
        }

        for w in word_items:
            if isinstance(w, dict):
                ws = float(w.get("start", 0.0))
                we = float(w.get("end", ws))
                wt = w.get("text", "")
                wc = w.get("confidence", None)
            else:
                ws = float(getattr(w, "start", 0.0))
                we = float(getattr(w, "end", ws))
                wt = getattr(w, "word", "")
                wc = getattr(w, "confidence", None)

            word = {
                "start": ws,
                "end": we,
                "text": str(wt or "").strip(),
                "confidence": wc,
            }
            if word["text"]:
                seg["words"].append(word)
                words_all.append(word)

        segments.append(seg)

    transcript: Dict = {
        "source": str(src),
        "model": model_size,
        "language": language,
        "task": task,
        "duration": _ffprobe_duration(src),
        "segments": segments,
        "words": words_all,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    return str(out_path)
