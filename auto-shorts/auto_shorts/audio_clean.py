import subprocess
from pathlib import Path
from typing import Optional


def clean_audio(input_path: str, output_path: str, use_noisereduce: bool = False) -> str:
    """Apply denoise + loudness normalization to an audio-containing media file.

    By default uses `ffmpeg` filters (`afftdn` + `loudnorm`). If `use_noisereduce` is True and
    the `noisereduce` and `soundfile` packages are available, it will attempt a waveform-level
    denoise pass.
    """
    inp = Path(input_path)
    out = Path(output_path)

    if use_noisereduce:
        try:
            import noisereduce as nr
            import soundfile as sf
            import numpy as np
        except Exception:
            use_noisereduce = False

    if use_noisereduce:
        # extract audio to temporary WAV
        tmp_wav = out.with_suffix(".tmp.wav")
        cmd = ["ffmpeg", "-y", "-i", str(inp), "-vn", "-ac", "1", "-ar", "16000", str(tmp_wav)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg extract failed: " + proc.stderr)

        data, sr = sf.read(str(tmp_wav))
        # estimate noise from first 0.5s
        noise_clip = data[: int(0.5 * sr)] if len(data) > sr // 2 else None
        if noise_clip is None:
            reduced = data
        else:
            reduced = nr.reduce_noise(y=data, sr=sr, y_noise=noise_clip)
        sf.write(str(tmp_wav), reduced, sr)
        # re-mux cleaned audio back into output with loudnorm
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(inp),
            "-i",
            str(tmp_wav),
            "-map",
            "0:v?",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            tmp_wav.unlink()
        except Exception:
            pass
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg remux failed: " + proc.stderr)
        return str(out)

    # default ffmpeg path
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(inp),
        "-af",
        "afftdn, loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v",
        "copy",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg audio_clean failed: " + proc.stderr)
    return str(out)

