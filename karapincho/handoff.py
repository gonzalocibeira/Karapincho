# SPDX-License-Identifier: GPL-3.0-or-later
"""Local folder handoff. External exports are never owned by job cleanup."""
import ctypes
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import config
from .chart import validate_chart
from .export import download_name
from .media import read_json, write_json

FILES = ('song.txt', 'audio.mp3', 'video.mp4', 'cover.jpg')
# Serialize filesystem operations with rebuild/retry/delete in the API.
LOCK = threading.RLock()
PICKER_LOCK = threading.Lock()


class Conflict(ValueError):
    pass


@contextmanager
def locked():
    with LOCK:
        yield


def choose_folder():
    if not PICKER_LOCK.acquire(blocking=False):
        raise ValueError('A folder picker is already open. Finish or cancel it first.')
    try:
        return _choose_folder()
    finally:
        PICKER_LOCK.release()


def _choose_folder():
    if sys.platform != 'darwin':
        raise ValueError('Folder selection requires macOS.')
    script = '''try
return POSIX path of (choose folder with prompt "Choose your karaoke Songs folder")
on error number -128
return ""
end try'''
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError('Folder selection timed out. Please try again.') from None
    if result.returncode:
        raise ValueError('Could not open the folder picker. Please try again.')
    return result.stdout.strip() or None


def destination_folder(value):
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Choose an existing karaoke Songs folder.')
    # Cleanup must never be able to reach the karaoke copy.
    if root == config.DATA or config.DATA in root.parents:
        raise ValueError('Choose a Songs folder outside Karapincho’s working data folder.')
    return root


def fingerprint(folder):
    digest = hashlib.sha256()
    for name in FILES:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('The song package is incomplete or contains linked files.')
        digest.update(name.encode() + b"\0")
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
    return digest.hexdigest()


def matches(folder, expected):
    try:
        return not folder.is_symlink() and fingerprint(folder) == expected
    except (OSError, ValueError):
        return False


def publish_new(source, target):
    """Atomically publish without clobbering a folder created by another app."""
    if sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(os.fsencode(source), os.fsencode(target), 4):  # RENAME_EXCL
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise Conflict('A song appeared at the destination. Please choose again.')
            raise OSError(error, os.strerror(error))
    else:
        if target.exists() or target.is_symlink():
            raise Conflict('A song appeared at the destination. Please choose again.')
        source.rename(target)


def recover_publication(journal):
    """Recover an interrupted rename on the next handoff, without discarding the old copy."""
    if not journal.exists():
        return
    entry = read_json(journal)
    target, backup = Path(entry['target']), Path(entry['backup'])
    if backup.exists():
        if not target.exists():
            publish_new(backup, target)
        elif matches(target, entry['fingerprint']):
            shutil.rmtree(backup)
        else:
            raise ValueError(f'An interrupted export needs review. Your previous copy is at {backup}')
    staging = Path(entry['staging'])
    if staging.exists():
        shutil.rmtree(staging)
    journal.unlink()
    return entry if matches(target, entry["fingerprint"]) else None


def export_song(store, job_id, collision='ask'):
    with locked():
        job = store.get(job_id)
        if job['status'] != 'completed' or job['cleaned_at'] is not None:
            raise ValueError('This song has no completed local package to export.')
        value = store.settings().get('songs_folder')
        if not value:
            raise ValueError('Choose your karaoke Songs folder first.')
        root = destination_folder(value)
        source = config.DATA / 'library' / job_id
        validate_chart((source / 'song.txt').read_text(encoding='utf-8-sig'), source)
        signature = fingerprint(source)
        journals = config.DATA / 'exports'
        journals.mkdir(exist_ok=True)
        journal = journals / f'{job_id}.json'
        recovered = recover_publication(journal)
        if (recovered and recovered['fingerprint'] == signature
                and Path(recovered['target']).parent == root):
            store.update(job_id, export_receipt={'path': recovered['target'], 'fingerprint': signature,
                                                'exported_at': time.time()})
            return store.get(job_id)
        receipt = job['export_receipt']
        old = Path(receipt.get('path', ''))
        if receipt.get('fingerprint') == signature and old.parent == root and matches(old, signature):
            return job
        target = root / download_name(source)
        # A previous publication may have completed before its receipt was committed.
        if matches(target, signature):
            store.update(job_id, export_receipt={'path': str(target), 'fingerprint': signature,
                                                'exported_at': time.time()})
            return store.get(job_id)
        exists = target.exists() or target.is_symlink()
        identity = (target.lstat().st_dev, target.lstat().st_ino) if exists else None
        if exists and collision == 'ask':
            raise Conflict(f'“{target.name}” already exists in your Songs folder.')
        if exists and collision == 'keep_both':
            index = 2
            while target.exists() or target.is_symlink():
                target = root / f'{download_name(source)} ({index})'
                index += 1
        elif exists and (target.is_symlink() or not target.is_dir()):
            raise ValueError('Cannot replace a linked folder or a file. Choose Keep both.')
        required = sum((source / name).stat().st_size for name in FILES)
        if shutil.disk_usage(root).free < required + 1024 * 1024:
            raise ValueError('Not enough free space in the Songs folder. Free space and retry Add to karaoke.')
        staging = Path(tempfile.mkdtemp(prefix='.karapincho-', dir=root))
        backup = root / (staging.name + '.previous')
        try:
            # Record staging before copying so a process interruption cannot leave
            # an untracked partial package on the external volume.
            write_json(journal, {'target': str(target), 'backup': str(backup),
                                 'staging': str(staging), 'fingerprint': signature})
            for name in FILES:
                shutil.copyfile(source / name, staging / name)
            validate_chart((staging / 'song.txt').read_text(encoding='utf-8-sig'), staging)
            if fingerprint(staging) != signature:
                raise ValueError('The copied song did not pass verification. Please retry.')
            if target.exists() or target.is_symlink():
                current_identity = (target.lstat().st_dev, target.lstat().st_ino)
                if collision != 'replace' or identity != current_identity:
                    raise Conflict('A song appeared at the destination. Please choose again.')
                publish_new(target, backup)
            try:
                publish_new(staging, target)
            except BaseException:
                if backup.exists():
                    publish_new(backup, target)
                raise
            store.update(job_id, export_receipt={'path': str(target), 'fingerprint': signature,
                                                'exported_at': time.time()})
            if backup.exists():
                shutil.rmtree(backup)
            journal.unlink(missing_ok=True)
            return store.get(job_id)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def cleanup_size(job_id):
    total = 0
    for category in ('jobs', 'library'):
        root = config.DATA / category / job_id
        if root.is_symlink() or not root.exists():
            continue
        for directory, _, names in os.walk(root, followlinks=False):
            for name in names:
                path = Path(directory) / name
                if not path.is_symlink():
                    total += path.stat().st_size
    return total


def cleanup(store, job_id):
    with locked(), store.connect() as db:
        recovered = recover_publication(config.DATA / 'exports' / f'{job_id}.json')
        db.execute('BEGIN IMMEDIATE')
        if recovered:
            receipt = {'path': recovered['target'], 'fingerprint': recovered['fingerprint'],
                       'exported_at': time.time()}
            db.execute('UPDATE jobs SET export_receipt=? WHERE id=?', (json.dumps(receipt), job_id))
        job = store.decode(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
        if job['status'] not in ('completed', 'failed', 'cancelled'):
            raise ValueError('Cancel this job and wait for it to stop before cleanup.')
        for category in ('jobs', 'library'):
            root = config.DATA / category / job_id
            if root.is_symlink():
                root.unlink()
            elif root.exists():
                shutil.rmtree(root)
        db.execute("UPDATE jobs SET cleaned_at=?,updated=?,lyric_settings='{}' WHERE id=?",
                   (time.time(), time.time(), job_id))
    return store.get(job_id)
