if [ "$EUID" -ne 0 ]
	then echo "Need to run as root"
	exit
fi

source_dir=`pwd`

echo "Killing UERANSIM-eNodeB"

pkill -2 -f nr-gnb

echo "Killed UERANSIM-eNodeB"


