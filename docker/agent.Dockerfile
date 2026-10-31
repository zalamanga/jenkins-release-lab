FROM docker:29.9.1-cli@sha256:6fae2214c3121a28d5aa639d09032f61310b7c9c75ffbad1025f261a1b621800 AS dockercli
FROM jenkins/inbound-agent:jdk21@sha256:5069347cd3e72e5924e54c04fceb67209b41c8d0a3ab1c2b3f740e5fb2fab92a

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 git ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /workspace /lab \
    && chown jenkins:jenkins /workspace /lab
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
USER jenkins
WORKDIR /workspace
