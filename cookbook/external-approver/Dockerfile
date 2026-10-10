FROM python:3.12.12-slim
WORKDIR /app
COPY connector.py /app/connector.py
USER 65532:65532
ENTRYPOINT ["python", "-u", "/app/connector.py", "--config", "/config/connector.json"]
