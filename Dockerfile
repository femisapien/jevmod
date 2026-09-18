FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY jevmod ./jevmod
RUN pip install --no-cache-dir . && useradd -m app && mkdir -p /data && chown app /data
USER app
ENV JEVMOD_DB=/data/jevmod.sqlite
VOLUME ["/data"]
# choose one: api | discord | telegram | reddit
ENV JEVMOD_ROLE=api
ENV JEVMOD_HOST=0.0.0.0
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,sys,urllib.request; sys.exit(0 if os.environ.get('JEVMOD_ROLE')!='api' else (0 if urllib.request.urlopen('http://127.0.0.1:8080/v1/health',timeout=3).status==200 else 1))"
CMD ["python", "-m", "jevmod"]
