#!/usr/bin/env python3
import os
import psutil
import subprocess
import sys
import time


WAIT = 2
# HOUR = 60*60
COMPUTE_TIME = 10*60

CORE_PROC_GRP = [
    "5gc",
    "open5gs-nrfd",
    "open5gs-scpd",
    "open5gs-upfd",
    "open5gs-smfd",
    "open5gs-amfd",
    "open5gs-ausfd",
    "open5gs-udmd",
    "open5gs-pcfd",
    "open5gs-nssfd",
    "open5gs-bsfd",
    "open5gs-udrd",
]


def start_core(conf_path, out_dir):
    with open(os.path.join(out_dir, "5gc.stdout"), "w") as out, \
         open(os.path.join(out_dir, "5gc.stderr"), "w") as err:
        cfg = os.path.join(conf_path)
        # subprocess.Popen(args=["5gc", "-c", cfg], stdout=sys.stdout, stderr=sys.stderr, 
        subprocess.Popen(args=["5gc", "-c", cfg], stdout=out, stderr=err, 
                         start_new_session=True)
        time.sleep(2)

def kill_core():
    for name in CORE_PROC_GRP:
        try:
            subprocess.run(["pkill", "-2", "-f", f"{name}"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
        except (FileNotFoundError, KeyboardInterrupt):
            pass


def lcov_reset_counters(cov_dir):
    subprocess.run(["lcov", "-d", cov_dir, "-z"], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def lcov_capture(cov_dir, idx, jdx):
    print("CAPTURING COVERAGE: ", idx, jdx, cov_dir)
    subprocess.run(["lcov", "-d", cov_dir, "-c", "-o", f"app{idx}_{jdx}.info", "--ignore-errors", "range", "--rc", 
                    "lcov_branch_coverage=1"], 
                   stdout=sys.stdout, stderr=sys.stderr)


def core_up():
    res = list()
    up_processes = list()
    for p in psutil.process_iter():
        try:
            up_processes.append(p.name())
        except psutil.NoSuchProcess:
            continue
    for name in CORE_PROC_GRP:
        if name in up_processes:
            res.append(True)
        else:
            res.append(False)
    return res


def sleep(secs, et):
    time.sleep(secs)
    return et + secs


def restart_core(core_path, out_dir):
    kill_core()
    start_core(core_path, out_dir)


def get_args():
    if len(sys.argv) < 4:
        print("usage: ./5gc.py /path/to/5gc/config /path/to/open5gs /path/to/logs")
        sys.exit(1)
    return (sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    conf_path, cov_dir, out_dir = get_args()
    restart_core(conf_path, out_dir)
    lcov_reset_counters(cov_dir)
    start_time = time.time()
    # idx = 0
    # while True:
    for hr_idx in range(0, 24):
        for mnt_idx in range(0, 6): # collect data every 10 minutes
            print("Hour, Minute : {}, {}".format(hr_idx, mnt_idx))
            try:
                res = core_up()
                if not all(res):
                    print(f"some of core group processes is crashed {res}. Respawning ...")
                    restart_core(conf_path, out_dir)
                    time.sleep(5)
                    
                time.sleep(COMPUTE_TIME)
                elapsed_time = time.time() - start_time
                if elapsed_time > COMPUTE_TIME:
                    start_time = time.time()
                    kill_core()
                    time.sleep(WAIT)
                    lcov_capture(cov_dir, hr_idx, mnt_idx)
                    # idx += 1
                
            except KeyboardInterrupt:
                kill_core()
                sys.exit(0)

