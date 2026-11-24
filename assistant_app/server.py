"""Explicitly approved local llama-server process manager."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path


class ServerManager:
    def __init__(self):
        self.process = None

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, executable, model, gpu_layers=0, context=4096, port=8080):
        if self.is_running():
            raise RuntimeError('Локальный сервер уже запущен')
        exe = Path(executable).expanduser().resolve(strict=True)
        model_path = Path(model).expanduser().resolve(strict=True)
        if exe.name.lower() != 'llama-server.exe' or not exe.is_file():
            raise ValueError('Выберите llama-server.exe из проверенного комплекта')
        if model_path.suffix.lower() != '.gguf' or not model_path.is_file():
            raise ValueError('Выберите файл модели GGUF')
        gpu_layers, context, port = int(gpu_layers), int(context), int(port)
        if not 0 <= gpu_layers <= 100 or not 512 <= context <= 32768 or not 1024 <= port <= 65535:
            raise ValueError('Неверные параметры сервера')
        argv = [str(exe), '-m', str(model_path), '--host', '127.0.0.1', '--port', str(port),
                '-c', str(context), '-ngl', str(gpu_layers)]
        self.process = subprocess.Popen(argv, cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return self.process.pid

    def stop(self):
        if not self.is_running():
            return False
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=4)
        return True
