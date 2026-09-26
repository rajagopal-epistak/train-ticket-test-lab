FROM docker.io/library/python:3.12-slim
RUN pip install --no-cache-dir requests==2.32.3
WORKDIR /opt/driver
COPY autoquery ./autoquery
COPY driver.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "driver.py"]
