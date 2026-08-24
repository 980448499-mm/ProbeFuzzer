#!/usr/bin/env python3

import subprocess

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

if __name__ == "__main__":
    # pass
    killUE()
    killGNB()
    killCore()
