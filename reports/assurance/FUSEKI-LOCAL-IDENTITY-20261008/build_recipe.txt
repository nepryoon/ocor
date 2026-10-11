FROM eclipse-temurin@sha256:db1689535962d757a5adabf57387584ed543d38c0b9d1fe870123ea362ad73b0

ARG FUSEKI_SHA512=ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132
COPY apache-jena-fuseki.tar.gz /tmp/apache-jena-fuseki.tar.gz
RUN echo "${FUSEKI_SHA512}  /tmp/apache-jena-fuseki.tar.gz" | sha512sum -c - \
    && mkdir -p /opt/fuseki /var/lib/fuseki \
    && tar --extract --gzip --file /tmp/apache-jena-fuseki.tar.gz --strip-components=1 --directory /opt/fuseki \
    && rm /tmp/apache-jena-fuseki.tar.gz \
    && chown -R 10001:0 /opt/fuseki /var/lib/fuseki
USER 10001
WORKDIR /var/lib/fuseki
EXPOSE 3030
ENTRYPOINT ["/opt/fuseki/fuseki-server"]
CMD ["--mem", "/ocor"]
