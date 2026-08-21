FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/cuemix/backend:/opt/cuemix

RUN groupadd --system cuemix && useradd --system --gid cuemix --home /opt/cuemix cuemix

COPY studio-ai-service/requirements.txt /tmp/studio-ai-requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/studio-ai-requirements.txt

WORKDIR /opt/cuemix
COPY backend/app /opt/cuemix/backend/app
COPY studio-ai-service/studio_ai /opt/cuemix/studio_ai
RUN chown -R cuemix:cuemix /opt/cuemix

USER cuemix
EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "studio_ai.main:app", "--host", "0.0.0.0", "--port", "8001"]
