"""Durable sequential A/B supervisor; launched by Windows Task Scheduler.

No retries, no test evaluation, no network: uses the already cached checkpoint.
All child output and atomic status remain on the training PC, not in SSH memory.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


def now():
    return datetime.now(timezone.utc).isoformat()


def signal_completion(name):
    if not name:
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenEventW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.OpenEventW.restype = ctypes.c_void_p
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.SetEvent.restype = ctypes.c_bool
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


def supervise(args):
    project = Path(args.project).resolve()
    runtime = Path(args.runtime_root).resolve()
    destination = Path(args.run_dir).resolve()
    python = runtime / '.venv-rubert/Scripts/python.exe'
    if not python.is_file() or not (project / 'dataset/manifest.json').is_file():
        raise ValueError('environment or frozen dataset is missing')
    if not (runtime / '.parsevk-training-root').is_file():
        raise ValueError('runtime is not a managed training root')
    if destination.parent != runtime / 'outputs':
        raise ValueError('run-dir must be directly under managed runtime outputs')
    destination.mkdir(exist_ok=False)
    status = {'status': 'running', 'started_utc': now(), 'supervisor_pid': os.getpid(),
              'source_commit': args.source_commit, 'max_length': 512,
              'epochs_each': 3, 'batch_size': 2, 'accumulation': 8,
              'seed': 20261107, 'network_disabled': True, 'tasks': []}

    def save():
        tmp = destination / 'status.tmp'
        tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(destination / 'status.json')

    environment = os.environ.copy()
    environment.update({'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1',
                        'HF_HOME': str(runtime / 'cache/huggingface'),
                        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                        'HF_HUB_DISABLE_SYMLINKS_WARNING': '1'})
    save()
    try:
        for task in ('A', 'B'):
            command = [str(python), '-u', '-m', 'src.rubert_training', 'train',
                       '--dataset', str(project / 'dataset'), '--task', task,
                       '--output', str(destination / ('model_' + task)),
                       '--epochs', '3', '--max-length', '512', '--batch-size', '2',
                       '--accumulation', '8', '--seed', '20261107']
            record = {'task': task, 'started_utc': now(), 'status': 'starting', 'command': command}
            status['tasks'].append(record); save()
            with (destination / (task + '_stdout.log')).open('wb') as out, \
                 (destination / (task + '_stderr.log')).open('wb') as err:
                child = subprocess.Popen(command, cwd=project, env=environment, stdout=out, stderr=err)
                record.update(pid=child.pid, status='running'); save()
                code = child.wait()
            record.update(returncode=code, finished_utc=now(), status='completed' if code == 0 else 'failed')
            if code != 0:
                status['status'] = 'failed'; save()
                break
            if not (destination / ('model_' + task) / 'completed.json').is_file():
                raise RuntimeError('child returned success without completion artifact')
            save()
        else:
            status['status'] = 'completed'
    except Exception as error:
        status.update(status='failed', error_type=type(error).__name__, error=str(error))
    finally:
        status['finished_utc'] = now(); save()
    return 0 if status['status'] == 'completed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--runtime-root', required=True)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--event-name')
    args = parser.parse_args()
    try:
        return supervise(args)
    finally:
        # Notification is best-effort: a lost SSH waiter must never change the
        # actual training result or cause a rerun. Task Scheduler owns the job.
        try:
            signal_completion(args.event_name)
        except Exception as error:
            print('Completion notification failed: ' + type(error).__name__, file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
