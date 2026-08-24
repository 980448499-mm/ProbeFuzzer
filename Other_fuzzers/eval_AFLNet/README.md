# AFLNet

## Build & Run
1. Clone CoreFuzzer, UERANSIM, and AFLNet:

2. Build a docker image to evaluate AFLNet
```shell
docker image build -t corefuzzer:aflnet .
```

3. Create a container:
```shell
# use different names for different runs
docker run --privileged --device /dev/net/tun:/dev/net/tun -v $(pwd):/corefuzzer --name corefuzzer_aflnet_1a -it corefuzzer:aflnet bash
./scripts/init_db.py /corefuzzer_deps/open5gs/
cp .env.example .env
```
4. Build AFLNet and CoreFuzzer wrapper:
```shell
cd eval/aflnet
gcc tutorials/corefuzzer/nr-ue.c -o nr-ue
make clean all
cd llvm_mode
make
cd ../../..
```

5. Config `nr-ue`: Make sure the following section can be found in `nu-ue` config file 
at `/corefuzzer_deps/ueransim/config/open5gs-ue.yaml`.
```yaml
StateLearner:
  family: 'inet'  # inet or unix
  addr: '127.0.0.1'  # unix sock name; any
  port: 13130  # ignored for unix family
```

6. Run CoreNetwork, GNB, and AFLNet in separate teminals:
```shell
mkdir -p eval/aflnet-out
cd eval/aflnet-out
../5gc.py /corefuzzer/sample.yaml /corefuzzer_deps/open5gs/ .

# use the docker name used in step 3
docker exec -it corefuzzer_aflnet_1a bash
cd eval/aflnet-out
../nr-gnb.sh > nr-gnb.stdout 2> nr-gnb.stderr

# use the docker name used in step 3
docker exec -it corefuzzer_aflnet_1a bash
cd eval/aflnet-out
AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 AFL_SKIP_CPUFREQ=1 ../aflnet/afl-fuzz -d -n -i ../aflnet/tutorials/corefuzzer/in -o fuzzer -N tcp://127.0.0.1/13130 -w 1000 -W 4 -m 1G -K -P 5GC -D 10000 -q 3 -s 3 -E -R ../aflnet/nr-ue
```

Note: If AFLNET is not running with some errors (No server states have been detected. Server responses are likely empty!),

i. Check htop if `nr-ue` is running. If so, terminate that.
ii. If still not working, try with some random number between 1 to 10000 (e.g. 100) like the following:  

```sh
echo 100 > .imsi_offset
../aflnet/nr-ue
```
Then ctrl+c. Wait couple minutes. Try to run AFLNET again.

## Usage
- `-d`: quick & dirty mode (skips deterministic steps)
- `-n`: fuzz without instrumentation (dumb mode)
- `-i`: input directory with test cases
- `-o`: output directory for fuzzer findings
- `-N`: server information (e.g., tcp://127.0.0.1/8554)
- `-w`: waiting time (in micro seconds) for receiving follow-up responses (the default value is 1000. you can increase in case of unresponsiveness)
- `-W`: waiting time (in miliseconds) for receiving the first response to each input sent (the default is 1 which is not enough for `nr-ue`)
- `-m`: memory limit for child process (50 MB - the default is not enough for `nr-ue`. Thread creation will fail with EAGAIN).
- `-K`: send SIGTERM to gracefully terminate `nr-ue`
- `-P`: application protocol to be tested
- `-D`: waiting time (in micro seconds) for the server to initialize
- `-q`: state selection algorithm (See aflnet.h for all available options)
- `-s`: seed selection algorithm (See aflnet.h for all available options)
- `-E`: enable state aware mode (see README.md)
- `-R`: enable region-level mutation operators (see README.md)

## Debugging
you can set `AFLNET_DEBUG=1` to enable verbose logging.

## Input Seeds
The input file format is as simple as one message per line. Each message has for parts:
```
[header]_[hex_bytes]_[SECMOD]_[SHT]
```
The `header` is the fixed string `aflnetMessage`. The `hex_bytes` is valid as long as it contains only hex characters `[0-9a-fA-F]`. The `SECMOD` and `SHT` are integers.
For example:
```
aflnetMessage_7E004179000D0199F9070000000000000000701001002E04F0F0F0F02F020101530100:1:0
```