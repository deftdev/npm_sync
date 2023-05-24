FROM python:3.9-alpine

RUN apk update && \
    apk upgrade --available && sync

COPY ./source/requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY ./source/sync-nginx.py /app/sync-nginx.py

# Keep the container running
CMD [ "python", "app/sync-nginx.py" ]
