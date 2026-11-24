"""Read-only local GGUF inventory and model sizing, without running model code."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

MAX_ENTRIES = 500
GGUF_MAGIC = b"GGUF"


def inspect_model(path):
    """Inspect an explicitly selected regular GGUF file; never follow symlinks."""
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.suffix.lower() != '.gguf':
        raise ValueError('Ожидается обычный файл GGUF без символьной ссылки')
    size = p.stat().st_size
    if size < 8:
        raise ValueError('Файл слишком мал для формата GGUF')
    with p.open('rb') as fp:
        if fp.read(4) != GGUF_MAGIC:
            raise ValueError('Неверная сигнатура GGUF')
        fmt = int.from_bytes(fp.read(4), 'little')
    if fmt < 1 or fmt > 3:
        raise ValueError('Неподдерживаемая версия заголовка GGUF')
    return {'name': p.name, 'path': str(p.absolute()), 'size': size, 'version': fmt}


def inventory(folder, max_entries=MAX_ENTRIES):
    """Top-level only, no traversal and no automatic discovery of user files."""
    directory = Path(folder)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Нужно выбрать обычную папку моделей')
    if not 1 <= int(max_entries) <= MAX_ENTRIES:
        raise ValueError('Недопустимый лимит файлов')
    found = []
    skipped = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.lower().endswith('.gguf'):
                continue
            if len(found) >= max_entries:
                skipped += 1
                continue
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    skipped += 1
                    continue
                found.append(inspect_model(entry.path))
            except (ValueError, OSError):
                skipped += 1
    return {'models': sorted(found, key=lambda m: m['name'].casefold()), 'skipped': skipped}


def checksum(path, max_bytes=14 * 1024**3):
    """SHA-256 on demand, bounded to avoid hashing huge untrusted files."""
    info = inspect_model(path)
    if info['size'] > max_bytes:
        raise ValueError('Модель превышает лимит проверки SHA-256')
    sha = hashlib.sha256()
    with open(info['path'], 'rb') as fp:
        while chunk := fp.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


def guidance(model_bytes, available_vram_gb=8):
    """Approximate conservative storage/VRAM hints, not GPU compatibility claims."""
    gb = model_bytes / 1024**3
    if gb > available_vram_gb * 0.70:
        return 'Модель крупная для 8 ГБ VRAM: начните с CPU и меньшего контекста.'
    return 'Размер файла умеренный; работа на RX 580 через Vulkan требует отдельной проверки.'
