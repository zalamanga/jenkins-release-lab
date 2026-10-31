FROM jenkins/jenkins:2.580.2-jdk21@sha256:74401de6a6f92e1afe1b02d1c8e3d0c33f263bfb5275dd8813f9150355f2367b

COPY --chown=jenkins:jenkins jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
COPY --chown=jenkins:jenkins jenkins/plugins.sha256 /usr/share/jenkins/ref/plugins.sha256
RUN jenkins-plugin-cli --latest=false --plugin-file /usr/share/jenkins/ref/plugins.txt \
    && cd /usr/share/jenkins/ref/plugins \
    && sha256sum --check ../plugins.sha256 \
    && test "$(find . -maxdepth 1 -name '*.jpi' | wc -l)" -eq "$(wc -l < ../plugins.txt)" \
    && git --version
