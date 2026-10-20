#!/usr/bin/env python3
import os
import pathlib
import re
import subprocess
import sys

cron = os.environ.get('CRON_SCHEDULE', '*/5 * * * *')
if not re.fullmatch(r'\S+(?:\s+\S+){4}', cron):
    sys.exit('CRON_SCHEDULE must contain five fields')
tz = os.environ.get('TZ', 'Europe/Berlin')
if not re.fullmatch(r'[A-Za-z0-9_+./-]+', tz) or '..' in tz:
    sys.exit('Invalid TZ')
localtime = pathlib.Path('/usr/share/zoneinfo') / tz
if not localtime.is_file():
    sys.exit('Unknown timezone')
p = pathlib.Path('/etc/localtime')
p.unlink(missing_ok=True)
p.symlink_to(localtime)
if len(sys.argv) > 1:
    subprocess.run(['python', '/usr/local/bin/archiver.py', sys.argv[1]], check=True)
    sys.exit(0)
# Cron doesn't inherit arbitrary container environment: explicitly provide validated settings.
settings = {
    'AGE_DAYS': os.environ.get('AGE_DAYS', '3'),
    'MAX_SIZE': os.environ.get('MAX_SIZE', '1 GiB'),
    'DRY_RUN': os.environ.get('DRY_RUN', 'true'),
    'DELETE_LARGE': os.environ.get('DELETE_LARGE', 'false'),
    'DOWNLOADS_DIR_HOST': os.environ.get('DOWNLOADS_DIR_HOST', '/downloads'),
}
for k, v in settings.items():
    if not re.fullmatch(r'[\w./ -]+', v):
        sys.exit(f'Invalid {k}')
job_env = ''.join(f'{k}={v!r}\n' for k, v in settings.items())
# cron env values with whitespace require quoting. Values validated above.
job = f'{cron} root /usr/local/bin/python /usr/local/bin/archiver.py >> /proc/1/fd/1 2>&1\n'
pathlib.Path('/etc/cron.d/archiver').write_text('SHELL=/bin/sh\nPATH=/usr/local/bin:/usr/bin:/bin\n' + job_env + job)
pathlib.Path('/etc/cron.d/archiver').chmod(0o644)
print(f'Cron schedule {cron}; mode={"sim" if settings["DRY_RUN".upper()].lower() in ("true", "yes", "1") else "run"}', flush=True)
os.execvp('cron', ['cron', '-f'])
