FROM python:3.13-slim

# Time zone rules come only from the pinned `tzdata` package, never from the base
# image, so offsets are the same wherever the image is built (§9).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONTZPATH= \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tablekeeper ./tablekeeper

EXPOSE 8080
CMD ["python", "-m", "tablekeeper"]
