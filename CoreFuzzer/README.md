# Installation

Open5GS is built from the **local source tree** (`../open5gs`, which carries the
ProbeFuzzer fault-injection changes in `src/amf/gmm-sm.c` / `gmm-handler.c`) at
image-build time. Campaigns call `prep_open5gs_stack.sh`, which upgrades the
running container if a newer build exists (`OPEN5GS_ENSURE_LATEST=false` to skip;
rebuild takes ~15–20 min).

To build the docker file, execute the following commands:
Copy ``UERANSIM_CoreTesting`` and ``open5gs`` inside this folder
```shell
cp -r ../UERANSIM_CoreTesting/ .
cp -r ../open5gs/ .
docker image build -t corefuzzer:sm .
```
Afterwards, you can obtain an interactive shell to a docker environment with 
CoreFuzzer installed by executing:
```shell
docker run --rm -v $(pwd):/corefuzzer --privileged -it corefuzzer:sm bash
```

```shell
mkdir logs
./scripts/init_db.py /corefuzzer_deps/open5gs/
cp .env.example .env
./core_fuzzer.py
```

