"""Optional Windows SAPI voice output, no pip modules needed."""
from __future__ import annotations
import subprocess


def say_windows(text):
    # No interpolated user text inside PowerShell code: data travels as UTF-16LE base64.
    import base64
    import json
    safe_text = text[:2000]
    encoded = base64.b64encode(safe_text.encode('utf-16le')).decode('ascii')
    code = ("Add-Type -AssemblyName System.Speech; "
            "$b=[Convert]::FromBase64String('" + encoded + "'); "
            "$s=[Text.Encoding]::Unicode.GetString($b); "
            "$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$v.Speak($s)")
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
