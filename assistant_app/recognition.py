"""Optional offline microphone transcription using Vosk; no network access.

Requires separately installed Vosk acoustic model and `vosk`, `sounddevice`.
"""
from __future__ import annotations
import json
from pathlib import Path


def transcribe_once(model_dir, *, seconds=8, rate=16000):
    folder = Path(model_dir).expanduser().resolve(strict=True)
    if not folder.is_dir() or not (folder / 'conf').is_dir() or not (folder / 'am').is_dir():
        raise ValueError('Выберите распакованную папку Vosk-модели с каталогами conf и am')
    if not 1 <= seconds <= 20:
        raise ValueError('Время записи: 1–20 секунд')
    try:
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer, SetLogLevel
    except ImportError as exc:
        raise RuntimeError('Для распознавания нужны библиотеки vosk и sounddevice') from exc
    SetLogLevel(-1)
    model = Model(str(folder))
    data = sd.rec(int(rate * seconds), samplerate=rate, channels=1, dtype='int16')
    sd.wait()
    rec = KaldiRecognizer(model, rate)
    rec.AcceptWaveform(data.tobytes())
    return json.loads(rec.FinalResult()).get('text', '').strip()
