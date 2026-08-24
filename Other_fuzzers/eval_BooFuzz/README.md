# Installation
To build the docker file, execute the following commands:
Copy ``UERANSIM_CoreTesting`` inside this folder
```shell
cp -r ../../UERANSIM_CoreTesting/ .
docker image build -t corefuzzer_boofuzz .
```
Afterwards, you can obtain an interactive shell to a docker environment with 
CoreFuzzer installed by executing:
```shell
docker run --rm -v $(pwd):/corefuzzer --privileged -it corefuzzer_boofuzz bash
```

```shell
mkdir logs
./scripts/init_db.py /corefuzzer_deps/open5gs/
cp .env.example .env
./run_hourly.py
```