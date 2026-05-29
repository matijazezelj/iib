FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY manager.py .
CMD ["uvicorn", "manager:app", "--host", "0.0.0.0", "--port", "8080"]
