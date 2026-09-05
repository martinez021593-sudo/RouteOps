FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ROUTEOPS_DATA_DIR=/data ROUTEOPS_SECURE_COOKIES=1
WORKDIR /app
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY . .
RUN mkdir -p /data/uploads
EXPOSE 8000
CMD ["gunicorn","--bind","0.0.0.0:8000","--workers","2","--threads","4","--timeout","120","wsgi:app"]
