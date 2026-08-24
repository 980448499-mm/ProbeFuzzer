if [ "$EUID" -ne 0 ]
	then echo "Need to run as root"
	exit
fi

echo "Killing open5gs"
pkill -9 -f 5gc
echo "Killing any already running open5gs process"
ps -ef | grep open5gs | grep -v grep | awk '{print $2}' | xargs kill -9

fuser -k -n tcp 7777

echo "Killed open5gs"