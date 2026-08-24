# Instructions

## Build UERANSIM

```sh
cd ../UERANSIM_CoreTesting
sudo apt update
sudo apt install make gcc g++ libsctp-dev lksctp-tools iproute2
sudo snap install cmake --classic
make
```

## Build Open5GS
First, MongoDB > 6.0 should be installed, please check https://www.mongodb.com/docs/manual/installation/ for platform specific instructions. 
```sh
sudo apt install gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg \
   --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt update
sudo apt install -y mongodb-org
sudo systemctl enable mongod
sudo systemctl start mongod
```

Then install dependencies and Open5GS. Ref: https://open5gs.org/open5gs/docs/guide/02-building-open5gs-from-sources/
```sh
sudo apt install python3-pip python3-setuptools python3-wheel ninja-build build-essential flex bison git cmake libsctp-dev libgnutls28-dev libgcrypt-dev libssl-dev libmongoc-dev libbson-dev libyaml-dev libnghttp2-dev libmicrohttpd-dev libcurl4-gnutls-dev libnghttp2-dev libtins-dev libtalloc-dev meson
if apt-cache show libidn-dev > /dev/null 2>&1; then
    sudo apt-get install -y --no-install-recommends libidn-dev
else
    sudo apt-get install -y --no-install-recommends libidn11-dev
fi
git clone https://github.com/open5gs/open5gs
cd open5gs
git fetch --tags
git checkout "$(git tag -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)"
meson build --prefix=`pwd`/install
ninja -C build
```

Add subscriber to Open5GS
```sh
python3 ./scripts/init_db.py ./open5gs
```

## Other dependencies
Install Java 11

## Configure and run Corelearner

Please modify `core.properties` to make sure the paths and passowrd are correct.
Please update the scripts under the directory `scripts` if necessory. 

To run the state learner, you can execute the following commands: 
```sh
java -jar Corelearner.jar core.properties
```

# Output
If the program runs successfully, you can find the output state machine under `logs` directory. 