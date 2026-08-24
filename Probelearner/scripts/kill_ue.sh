if [ "$EUID" -ne 0 ]
	then echo "Need to run as root"
	exit
fi

source_dir=`pwd`

echo "Killing UERANSIM-UE"

pkill -2 -f nr-ue

echo "Killed UERANSIM-UE"s


