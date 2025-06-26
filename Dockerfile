FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache tzdata \
    && apk add --no-cache --virtual .build-deps gcc musl-dev

COPY requirements.txt .
RUN pip install --no-cache-dir pip==23.1.2

RUN pip install --no-cache-dir -r requirements.txt

RUN apk del .build-deps

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
