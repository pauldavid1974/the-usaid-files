"""Generate local timestamped ASR and preserve the byte origin of its input."""
import json
import subprocess

import numpy as np

from faster_whisper import BatchedInferencePipeline, WhisperModel

from acquire import ROOT, digest, write_json


def transcribe():
    by_name = {}
    for folder in ("mirrors/files", "originals", "originals/additions"):
        by_name.update((path.name, path) for path in (ROOT / folder).glob("*.mp4"))
    model = BatchedInferencePipeline(WhisperModel(
        "base.en", device="cpu", compute_type="int8", cpu_threads=6,
        download_root=str(ROOT / ".models")))
    for path in sorted(by_name.values()):
        output = ROOT / "transcripts" / (path.stem + ".asr.json")
        sha = digest(path)
        if output.is_file() and json.loads(output.read_text(encoding="utf-8"))["sha256"] == sha:
            continue
        pcm = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
                              "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
                             check=True, stdout=subprocess.PIPE).stdout
        audio = np.frombuffer(pcm, dtype="<f4")
        segments, info = model.transcribe(audio, batch_size=8, beam_size=1, language="en")
        rows = [{"start": round(segment.start, 3), "end": round(segment.end, 3),
                 "text": segment.text.strip()} for segment in segments]
        assert rows and all(0 <= row["start"] < row["end"] <= info.duration + 1 for row in rows)
        write_json(output, {"engine": "faster-whisper base.en", "sha256": sha,
                            "input": path.relative_to(ROOT).as_posix(), "duration": info.duration,
                            "segments": rows})
        print(f"{path.name}: {len(rows)} segments, {info.duration:.1f}s", flush=True)


if __name__ == "__main__":
    transcribe()
