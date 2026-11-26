FROM python:3.12-slim

WORKDIR /app

# print()/log output reaches `docker logs` immediately instead of sitting in a buffer
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]

