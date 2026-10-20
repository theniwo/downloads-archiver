FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends cron tzdata && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir 'organize-tool==3.3.0'
COPY entrypoint.py archiver.py /usr/local/bin/
ENTRYPOINT ["python", "/usr/local/bin/entrypoint.py"]
