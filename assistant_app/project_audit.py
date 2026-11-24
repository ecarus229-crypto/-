"""Conservative offline code health report. Never executes, imports or uploads project code."""
from __future__ import annotations
import ast
import json
import re
from collections import Counter
from pathlib import Path
from . import workspace

MAX_SCAN_FILES = 600
MAX_READ_BYTES = 128 * 1024
MAX_RESULTS = 200
SUFFIXES = {'.py', '.json', '.js', '.jsx', '.ts', '.tsx', '.php', '.css', '.html', '.md', '.txt', '.yml', '.yaml', '.toml', '.ini', '.ps1'}
EXCLUDE_NAMES = {'.env', '.env.local', '.env.production', 'id_rsa', 'id_ed25519', 'credentials.json', 'secrets.json'}
SECRET_PATTERNS = (
    ('Возможный приватный ключ', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('Возможный токен', re.compile(r'(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password)\b\s*[=:]\s*[\'\"]?[^\s\'\";,#]{8,}')),
)
TODO_RE = re.compile(r'\b(?:TODO|FIXME|XXX)\b', re.I)


def _notice(kind, path, line, summary):
    return {'kind': kind, 'path': path, 'line': line, 'summary': summary}


def scan(root, max_files=MAX_SCAN_FILES):
    """Return bounded, local metadata/report; never embed source lines or credential values."""
    base = workspace.normalized_root(root)
    budget = max(1, min(int(max_files), MAX_SCAN_FILES))
    rows = workspace.list_files(base, limit=budget)
    counts = Counter()
    findings = []
    examined = 0
    skipped = 0
    truncated = False
    for name, size in rows:
        p = Path(name)
        if p.name.lower() in EXCLUDE_NAMES or p.suffix.lower() not in SUFFIXES or size > MAX_READ_BYTES:
            skipped += 1
            continue
        try:
            # workspace.read_text enforces no traversal and no symlink following.
            content = workspace.read_text(base, name)
        except (OSError, UnicodeError, workspace.WorkspaceError):
            skipped += 1
            continue
        examined += 1
        counts[p.suffix.lower()] += 1
        if p.suffix.lower() == '.py':
            try:
                ast.parse(content, filename=name)
            except SyntaxError as exc:
                findings.append(_notice('Синтаксис Python', name, exc.lineno or 0, 'Обнаружена синтаксическая ошибка'))
        elif p.suffix.lower() == '.json':
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                findings.append(_notice('Синтаксис JSON', name, exc.lineno, 'Не удалось разобрать JSON'))
        for line_number, line in enumerate(content.splitlines(), 1):
            if TODO_RE.search(line):
                findings.append(_notice('Задача в коде', name, line_number, 'Найдена пометка TODO/FIXME/XXX'))
            if any(pattern.search(line) for _, pattern in SECRET_PATTERNS):
                findings.append(_notice('Конфиденциальные данные', name, line_number, 'Возможный секрет: значение намеренно скрыто'))
            if len(findings) >= MAX_RESULTS:
                truncated = True
                break
        if truncated:
            break
    return {'base': str(base), 'scanned': examined, 'skipped': skipped,
            'counts': dict(sorted(counts.items())), 'findings': findings[:MAX_RESULTS],
            'truncated': truncated or len(rows) >= budget,
            'notes': 'Локальная эвристическая проверка. Не запускает код, не ищет уязвимости полностью и не гарантирует обнаружение секретов.'}


def render(report):
    lines = ['PERSONALAI — ЛОКАЛЬНЫЙ АУДИТ ПРОЕКТА',
             'Папка: ' + report['base'],
             f"Проверено файлов: {report['scanned']}; пропущено: {report['skipped']}",
             'Типы: ' + (', '.join(f'{k}: {v}' for k, v in report['counts'].items()) or 'не найдены'),
             'Результаты:']
    for finding in report['findings']:
        lines.append(f"{finding['path']}:{finding['line']} [{finding['kind']}] {finding['summary']}")
    if not report['findings']:
        lines.append('Проблем по проверяемым правилам не найдено.')
    if report['truncated']:
        lines.append('ВНИМАНИЕ: достигнут предел обхода/результатов, отчёт неполный.')
    lines.append(report['notes'])
    return '\n'.join(lines)
