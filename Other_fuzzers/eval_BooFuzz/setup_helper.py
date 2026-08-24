from dotenv import dotenv_values
import os, subprocess, time
# helper functions for start and kill the components

config = dotenv_values(".env")
# set IMSI offset
IMSI_OFFSET = 0
MAX_IMSI_OFFSET = 100

def startCore():
    with open("./logs/core.log", "w") as out:
        cfg = os.path.join(config["OPEN5GS_PATH"], "build", "configs", "sample.yaml")
        subprocess.Popen(args=["5gc", "-c", cfg], stdout=out, stderr=out, 
                         start_new_session=True)

def startUE():
    with open("./logs/ue.log", "w") as out:
        cfg = os.path.join(config["UERANSIM_PATH"], "config", "open5gs-ue.yaml")
        imsi = f"imsi-{999700000000001 + IMSI_OFFSET}"
        subprocess.Popen(args=["nr-ue", "-c", cfg, "-i", imsi], stdout=out, 
                         stderr=out, start_new_session=True)

def startGNB():
    with open("./logs/gnb.log", "w") as out:
        cfg = os.path.join(config["UERANSIM_PATH"], "config", "open5gs-gnb.yaml")
        subprocess.Popen(args=["nr-gnb", "-c", cfg], stdout=out, stderr=out, 
                         start_new_session=True)

def killCore():
    subprocess.run(["pkill", "-2", "-f", "5gc"], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc = subprocess.run(["ps", "-ef"], encoding='utf-8', stdout=subprocess.PIPE)
    for line in proc.stdout.split("\n"):
        if "open5gs" not in line:
            continue
        pid = line.split()[1]
        print(f"Killing pid {pid}")
        subprocess.run(["kill", "-2", pid])

def killUE():
    subprocess.run(["pkill", "-2", "-f", "nr-ue"], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def killGNB():
    subprocess.run(["pkill", "-2", "-f", "nr-gnb"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def sendRRCRelease():
    subprocess.Popen(args=["nr-cli", "UERANSIM-gnb-999-70-1", "--exec", "ue-release 1"])
    time.sleep(0.25)