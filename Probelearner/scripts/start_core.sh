if [ "$EUID" -ne 0 ]
	then echo "Need to run as root"
	exit
fi

echo "Launching start_core.sh"

source_dir=`pwd`
# May need to change here for open5gs path
cd ./open5gs

./build/tests/app/5gc ./build/configs/sample.yaml

cd "$source_dir"

echo "Finished launching start_core.sh"