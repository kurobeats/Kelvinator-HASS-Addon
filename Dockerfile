ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-cryptography \
    py3-cffi \
    jq \
    curl

RUN pip3 install --no-cache-dir --break-system-packages \
    broadlink==0.19.0 \
    paho-mqtt==2.0.0 \
    requests==2.31.0 \
    pycryptodome==3.20.0

COPY kelvinator_mqtt/ /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app
CMD ["/run.sh"]
