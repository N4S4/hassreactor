# hassreactor Docker image
# Build: docker build -t hassreactor .
# Run:   docker run -e HA_URL=... -e HA_TOKEN=... -v ./automations.py:/app/automations.py hassreactor

FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app

# Copy installed deps from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Install hassreactor from local source
COPY . /tmp/hassreactor
RUN pip install --no-cache-dir /tmp/hassreactor && rm -rf /tmp/hassreactor

# Default command — user mounts their automations.py
CMD ["python", "automations.py"]
