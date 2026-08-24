FROM ubuntu:22.04
LABEL "about"="CoreFuzzer base img"

ARG DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-suggests --no-install-recommends \
    gnupg curl ca-certificates systemctl \
    python3-pip python3-setuptools python3-wheel \
    ninja-build build-essential flex bison \
    git cmake iproute2 \
    libsctp-dev libgnutls28-dev libgcrypt-dev libssl-dev \
    libidn11-dev libmongoc-dev libbson-dev libyaml-dev \
    libnghttp2-dev libmicrohttpd-dev libcurl4-gnutls-dev libnghttp2-dev \
    libtins-dev libtalloc-dev libsctp-dev lksctp-tools \
    meson

# Install MongoDB (Tsinghua mirror: repo.mongodb.org is very slow/unreliable here)
RUN curl -fsSL https://pgp.mongodb.com/server-6.0.asc | \
    gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor && \
    echo "\
deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg] \
https://mirrors.tuna.tsinghua.edu.cn/mongodb/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | \
    tee /etc/apt/sources.list.d/mongodb-org-6.0.list && \
    apt-get update && apt-get install -y mongodb-org && \
    systemctl start mongod && systemctl enable mongod

# Install Open5GS from the LOCAL source tree (includes ProbeFuzzer fault-injection
# changes in src/amf/gmm-sm.c and gmm-handler.c). The local build/ dir is removed
# so the container rebuilds cleanly against this tree.
WORKDIR /corefuzzer_deps
COPY open5gs /corefuzzer_deps/open5gs
WORKDIR /corefuzzer_deps/open5gs
RUN rm -rf build install && mkdir install
RUN meson build --prefix=/ -Db_coverage=true && \
    ninja -C build
RUN cd build && ninja install && cd .. && cp build/tests/app/5gc /usr/bin/
COPY scripts/patch_open5gs_lab_sample.py /tmp/patch_open5gs_lab_sample.py
RUN python3 /tmp/patch_open5gs_lab_sample.py /corefuzzer_deps/open5gs/build/configs/sample.yaml

# Install UERANSIM
WORKDIR /corefuzzer_deps
COPY UERANSIM_CoreTesting /corefuzzer_deps/ueransim
WORKDIR /corefuzzer_deps/ueransim
RUN make -j`nproc` && cp build/nr-* /usr/bin/

# Install CoreFuzzer dependencies (Tsinghua pypi mirror for speed)
COPY requirements.txt /corefuzzer/requirements.txt
RUN pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple -r /corefuzzer/requirements.txt

# (lcov/perl coverage steps removed: not needed for the ProbeFuzzer protocol-violation
#  experiments, and the lcov git clone fails intermittently in this network.)

WORKDIR /corefuzzer
ENTRYPOINT systemctl start mongod && /bin/bash
