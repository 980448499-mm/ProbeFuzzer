#!/usr/bin/env python3
# Run BooFuzz queries on Core

import os, time, socket, string, json, atexit
from db_helper import *
from setup_helper import *

fuzzing_index:int
crash_count:int

# handle exit
def exit_handler():
    # clean up
    killCore()
    killGNB()
    killUE()
    index_file = open('./index.txt', 'w')
    index_file.write(f"{fuzzing_index}:{crash_count}")
    index_file.close()

# restart Core or release UE context
def reset(full: bool):    
    if full:
        print("start full reset")
        # restart Core
        killCore()
        killGNB()
        killUE()
        time.sleep(0.5)
        startCore()
        time.sleep(2.5)
        startGNB()
        time.sleep(0.1)
        startUE()
        time.sleep(0.1)
        print("reset done")       
        return IMSI_OFFSET + 1
    elif IMSI_OFFSET > MAX_IMSI_OFFSET:
        print("start full reset")
        # restart Core
        killCore()
        killGNB()
        killUE()
        time.sleep(0.5)
        startCore()
        time.sleep(2.5)
        startGNB()
        time.sleep(0.1)
        startUE()
        time.sleep(0.1)
        print("reset done") 
        return 0
    else:
        print("start reset")
        killGNB()
        killUE()
        time.sleep(0.5)
        startGNB()
        time.sleep(0.1)
        startUE()
        time.sleep(0.1)
        print("reset done")
        return IMSI_OFFSET + 1
    
# connect to UE
def connectUE():
    global UEsocket
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(1)
    UEsocket.connect(("localhost", 45678)) # TODO: add to config later
    print(UEsocket.recv(1024))

# connect to gNB
def connectGNB():
    global gNBsocket
    gNBsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    gNBsocket.settimeout(1)
    gNBsocket.connect(("localhost", 56789)) # TODO: add to config later
    print(gNBsocket.recv(1024))

def sendSymbol(symbol: string):
    UEsocket.send(symbol.encode())
    try:
        msg_out = UEsocket.recv(1024).decode().strip()
    except socket.timeout:
        msg_out = "null_action"
    return msg_out

# send a message to UERANSIM
def sendFuzzingMessage(msg):
    # get a base message from db
    UEsocket.send(msg)
    print("send message")
    print(msg)
    return

if __name__ == '__main__':
    if os.path.exists("./index.txt"):
        index_file = open('./index.txt', 'r')
        index_str = index_file.read()
        fuzzing_index = int(index_str.split(":")[0])
        crash_count = int(index_str.split(":")[1])
        index_file.close()
    else:
        fuzzing_index = 0
        crash_count = 0
    atexit.register(exit_handler) # register exit handler
    IMSI_OFFSET = reset(True) # reset before fuzzing loop
    full_reset = False
    fuzz_file=open('./fuzzing.txt', 'r')
    lines=fuzz_file.readlines()
    # main fuzzing loop
    while True:
        try:
            IMSI_OFFSET = reset(full_reset)
            connectUE()
            connectGNB()
            for i in range(10):
                fuzzMsg = lines[fuzzing_index]
                try:
                    sendSymbol("testMessage")
                    sendFuzzingMessage(fuzzMsg.encode())
                    time.sleep(0.1)
                except socket.timeout:
                    print("no response from UE")
                fuzzing_index += 1
                print(fuzzing_index)
            try:
                msg_gnb = gNBsocket.recv(1024).decode().strip()
                if "AMF is down" in msg_gnb:
                    full_reset = True
                    crash_count += 1
                    crash_file = open('./logs/crash.log', 'a')
                    crash_file.write(f"{fuzzing_index}, {crash_count}\n")
                    crash_file.close()
            except socket.timeout:
                print("no feedback from gNB")
        except Exception as e: # capture all not considered exceptions
            print(e)
            error_file = open('./logs/error.log', 'a')
            error_file.write(time.strftime("%Y-%m-%d %H:%M:%S ", time.localtime()))
            error_file.write(str(e)+"\n")
            error_file.close()
            continue
