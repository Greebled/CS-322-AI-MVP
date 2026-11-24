FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached when only app code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
ENTRYPOINT ["python", "-u"]
CMD ["app.py"]
