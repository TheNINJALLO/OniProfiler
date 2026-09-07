FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ONI_DATA_DIR=/data
WORKDIR /app
COPY controlplane/ /app/controlplane/
COPY LICENSE NOTICE /app/
RUN python -m pip install --no-cache-dir /app/controlplane && \
    useradd --uid 10001 --create-home oni && mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import os,urllib.request,urllib.parse; host=urllib.parse.urlsplit(os.environ['ONI_PUBLIC_ORIGIN']).netloc; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/healthz',headers={'Host':host}),timeout=3)"
CMD ["oniprofiler-server", "--host", "0.0.0.0", "--port", "8080"]
