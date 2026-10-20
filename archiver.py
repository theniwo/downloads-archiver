#!/usr/bin/env python3
"""Persistent first-observed / quiet-period gating for organize's move action."""
import json
import shutil
import uuid
from urllib.parse import quote
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime

SRC = pathlib.Path('/downloads')
DEST = pathlib.Path('/archive')
STATE = pathlib.Path('/state/seen.json')
MANIFEST = pathlib.Path('/tmp/eligible.json')
CONFIG = pathlib.Path('/tmp/organize.yaml')
TRASH = pathlib.Path('/trash')
HOST_DOWNLOADS = pathlib.Path(os.environ.get('DOWNLOADS_DIR_HOST', '/downloads'))

def size_bytes(raw):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([KMGTPE]?i?B)\s*', raw, re.I)
    if not match:
        raise ValueError('MAX_SIZE must look like 1 GiB')
    amount, unit = match.groups()
    unit = unit.upper()
    base = 1024 if 'I' in unit else 1000
    exp = 'KMGTPE'.index(unit[0]) + 1 if len(unit) > 1 else 0
    return float(amount) * base ** exp

def fingerprint(p):
    """Snapshot metadata, including nested files, with no symlink traversal."""
    records = []
    total = 0
    paths = [p]
    if p.is_dir():
        paths += sorted(p.rglob('*'), key=lambda x: str(x))
    for item in paths:
        s = item.lstat()
        if item.is_symlink():
            raise ValueError('symlink detected')
        if not (item.is_file() or item.is_dir()):
            raise ValueError('unsupported special file')
        rel = str(item.relative_to(p)) if item != p else '.'
        # Ignore directory mtimes: they change as items are moved or created;
        # children's listings and metadata capture actual changes.
        records.append((rel, 'd' if item.is_dir() else 'f', s.st_size if item.is_file() else 0,
                        s.st_mtime_ns if item.is_file() else 0))
        if item.is_file():
            total += s.st_size
    import hashlib
    digest = hashlib.sha256(json.dumps(records, separators=(',', ':')).encode()).hexdigest()
    return digest, total

def trash_file(src):
    """Freedesktop trash layout, visible in GNOME Files via ~/.local/share/Trash."""
    files = TRASH / 'files'
    info = TRASH / 'info'
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    # Unique destination plus info file; no clobbering even with existing names.
    while True:
        name = f'{src.name}.{uuid.uuid4().hex}'
        dst = files / name
        infofile = info / (name + '.trashinfo')
        if not dst.exists() and not infofile.exists():
            break
    original = str(HOST_DOWNLOADS / src.name)
    record = ('[Trash Info]\n'
              f'Path={quote(original, safe="/")}\n'
              f'DeletionDate={datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S")}\n')
    # Write metadata first. If move fails, remove metadata. If metadata remains
    # after a process crash, it does not imply deletion of the original file.
    with infofile.open('x') as f:
        f.write(record)
    try:
        shutil.move(str(src), str(dst))  # supports cross-filesystem moves
    except Exception:
        infofile.unlink(missing_ok=True)
        raise
    print('TRASHED', src.name, '->', dst, flush=True)

def main():
    if not SRC.is_dir() or not DEST.is_dir():
        sys.exit('Missing /downloads or /archive volume')
    age = float(os.environ.get('AGE_DAYS', '3'))
    if age <= 0:
        sys.exit('AGE_DAYS must be positive')
    limit = size_bytes(os.environ.get('MAX_SIZE', '1 GiB'))
    raw_delete = os.environ.get('DELETE_LARGE', 'false').lower()
    if raw_delete not in ('true', 'false'):
        sys.exit('DELETE_LARGE must be true or false')
    delete_large = raw_delete == 'true'
    if not delete_large and not TRASH.is_dir():
        sys.exit('Missing /trash mount (required with DELETE_LARGE=false)')
    now = time.time()
    data = {}
    if STATE.exists():
        data = json.loads(STATE.read_text())
    updated = {}
    eligible = []
    oversized = []
    for p in sorted(SRC.iterdir()):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            print('SKIP unsupported entry:', p.name, flush=True)
            continue
        try:
            digest, size = fingerprint(p)
        except (OSError, ValueError) as e:
            print('SKIP:', p.name, e, flush=True)
            continue
        old = data.get(p.name, {})
        since = old.get('since', now) if digest == old.get('fingerprint') else now
        updated[p.name] = {'fingerprint': digest, 'since': since}
        elapsed = now - since
        # File size cap preserves original script behaviour. Directories are unrestricted.
        if elapsed >= age * 86400:
            if p.is_dir() or size <= limit:
                eligible.append(p.name)
            else:
                oversized.append(p.name)
        status = 'LARGE' if p.name in oversized else ('READY' if p.name in eligible else 'WAIT ')
        print(f'{status} {p.name!r} ({elapsed/86400:.2f} days unchanged; {size} bytes)', flush=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(updated, indent=2, ensure_ascii=False))
    tmp.replace(STATE)
    MANIFEST.write_text(json.dumps(eligible, ensure_ascii=False))
    # Two separate rules: no traversal, move whole top-level folders.
    CONFIG.write_text('''rules:
  - name: Archive eligible top-level directories
    locations: /downloads
    targets: dirs
    filters:
      - python: |
          import json
          return path.name in json.load(open("/tmp/eligible.json"))
    actions:
      - move:
          dest: /archive/
          on_conflict: rename_new
  - name: Archive eligible top-level files
    locations: /downloads
    targets: files
    filters:
      - python: |
          import json
          return path.name in json.load(open("/tmp/eligible.json"))
    actions:
      - move:
          dest: /archive/
          on_conflict: rename_new
''')
    mode = sys.argv[1] if len(sys.argv) > 1 else ('sim' if os.getenv('DRY_RUN', 'true').lower() in ('true','1','yes') else 'run')
    if mode not in ('sim', 'run'):
        sys.exit('Usage: archiver.py [sim|run]')
    subprocess.run(['organize', 'check', str(CONFIG)], check=True)
    if eligible:
        print('Running organize', mode, 'for', len(eligible), 'items', flush=True)
        subprocess.run(['organize', mode, str(CONFIG)], check=True)
    for name in oversized:
        src = SRC / name
        # Recheck before destructive action; never follow symlinks.
        try:
            if src.is_symlink() or not src.is_file() or src.stat().st_size <= limit:
                print('SKIP changed item:', name, flush=True)
                continue
            if fingerprint(src)[0] != updated[name]['fingerprint']:
                print('SKIP changed item:', name, flush=True)
                continue
            if mode == 'sim':
                print('SIMULATE', 'DELETE' if delete_large else 'TRASH', name, flush=True)
            elif delete_large:
                src.unlink()
                print('DELETED', name, flush=True)
            else:
                trash_file(src)
        except OSError as e:
            print('ERROR oversized file:', name, e, file=sys.stderr, flush=True)
            raise
    if not eligible and not oversized:
        print('No eligible items.', flush=True)

if __name__ == '__main__':
    main()
