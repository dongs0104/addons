FROM python:3.12-slim

ENV LANG=C.UTF-8
ENV TZ=Asia/Seoul

RUN pip install --no-cache-dir paho-mqtt

COPY run.sh ezville.py packet.py devices.py /
RUN chmod a+x /run.sh

WORKDIR /share

CMD [ "/run.sh" ]
