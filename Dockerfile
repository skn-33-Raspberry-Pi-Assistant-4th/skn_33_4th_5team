# CUDA-enabled image shared by Django and the separately cancellable Quiz worker.
FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/web_app

COPY requirements-gpu.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-gpu.txt

COPY . .
