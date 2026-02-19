#ARG BUILD_FROM
#FROM $BUILD_FROM
FROM python:3.10

ENV LANG C.UTF-8

RUN python3 -m pip install paho-mqtt

COPY . /srv
RUN chmod a+x /srv/run_addon.sh

WORKDIR /share

CMD [ "/srv/run_addon.sh" ]
