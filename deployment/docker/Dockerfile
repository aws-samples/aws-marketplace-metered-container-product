FROM python:3.8-alpine3.10
COPY app/ /app
COPY deployment/docker/requirements.txt /requirements.txt 
RUN pip install -r requirements.txt
WORKDIR /app
CMD ["python", "api.py"]
