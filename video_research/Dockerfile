FROM python:3.12-slim
WORKDIR /app
COPY video_research/requirements.txt /app/video_research/requirements.txt
RUN pip install --no-cache-dir -r video_research/requirements.txt
COPY video_research /app/video_research
RUN useradd -m app && chown -R app /app
USER app
CMD ["python", "-m", "video_research.main", "api"]
