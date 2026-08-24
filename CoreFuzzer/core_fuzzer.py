#!/usr/bin/env python3
# Run queries on Core

import os, time, socket, string, json, atexit
from db_helper import *
from fsm_helper import *
from setup_helper import *

reset_count = 0

# handle exit
def exit_handler(fsm: FSM, fsm_sm: FSM):
    # clean up
    killCore()
    killGNB()
    killUE()
    fsm_file = open('./savedFSM.json', 'w')
    fsm_file.write(fsm.to_json())
    fsm_file.close()
    fsm_sm_file = open('./savedFSM_sm.json', 'w')
    fsm_sm_file.write(fsm_sm.to_json())
    fsm_sm_file.close()


# restart Core or release UE context
def reset(full: bool):   
    if full:
        print("start full reset")
        # restart Core
        fsm.refresh_paths()
        fsm_sm.refresh_paths()
        killCore()
        killGNB()
        killUE()
        time.sleep(0.5)
        startCore()
        time.sleep(10)
        startGNB()
        time.sleep(0.1)
        startUE()
        time.sleep(0.1)
        print("reset done") 
        setOffset(getOffset() + 1)
        return
    elif getOffset() > MAX_IMSI_OFFSET:
        print("start full reset")
        # restart Core
        killCore()
        killGNB()
        killUE()
        time.sleep(0.5)
        startCore()
        time.sleep(10)
        startGNB()
        time.sleep(0.1)
        startUE()
        time.sleep(0.1)
        print("reset done")
        setOffset(0)
        return
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
        setOffset(getOffset() + 1)
        return

# connect to UE
def connectUE():
    global UEsocket
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(1)
    UEsocket.connect(("localhost", 45678))
    print(UEsocket.recv(1024))

def connectUE2():
    global UEsocket
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(1)
    UEsocket.connect(("localhost", 45679))
    print(UEsocket.recv(1024))

def connectUE3():
    global UEsocket
    UEsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    UEsocket.settimeout(1)
    UEsocket.connect(("localhost", 45680))
    print(UEsocket.recv(1024))

# connect to gNB
def connectGNB():
    global gNBsocket
    gNBsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    gNBsocket.settimeout(1)
    gNBsocket.connect(("localhost", 56789))
    print(gNBsocket.recv(1024))

def sendSymbol(symbol: string):
    if "serviceRequest" in symbol:
        sendRRCRelease()
        time.sleep(0.1)
    if ":" in symbol:
        i = symbol.find(":")
        sendSymbol("testMessage")
        testMsg = symbol[i+1:]
        return sendFuzzingMessage(testMsg.encode())
    UEsocket.send(symbol.encode())
    try:
        msg_out = UEsocket.recv(1024).decode().strip()
    except socket.timeout:
        msg_out = "null_action"
    return msg_out

symbols_enabled = [
                   "registrationRequest", 
                   "registrationComplete",
                   "deregistrationRequest", 
                   "serviceRequest", 
                   "securityModeReject",
                   "authenticationResponse",
                   "authenticationFailure",
                   "deregistrationAccept",
                   "securityModeComplete",
                   "identityResponse",
                   "configurationUpdateComplete",
                   "gmmStatus",
                   "ulNasTransport",
                   "PDUSessionEstablishmentRequest",
                   "PDUSessionAuthenticationComplete",
                   "PDUSessionModificationRequest",
                   "PDUSessionModificationComplete",
                   "PDUSessionModificationCommandReject",
                   "PDUSessionReleaseRequest",
                   "PDUSessionReleaseComplete",
                   "gsmStatus"]

symbols_fsm = ["registrationRequest", 
               "registrationRequestGUTI", 
               "registrationComplete",
               "deregistrationRequest", 
               "serviceRequest", 
               "securityModeReject",
               "authenticationResponse",
               "authenticationFailure",
               "deregistrationAccept",
               "securityModeComplete",
               "identityResponse",
               "configurationUpdateComplete"]

symbols_sm = ["PDUSessionEstablishmentRequest",
              "PDUSessionAuthenticationComplete",
              "PDUSessionModificationRequest",
              "PDUSessionModificationComplete",
              "PDUSessionModificationCommandReject",
              "PDUSessionReleaseRequest",
              "PDUSessionReleaseComplete",
              "gsmStatus"]

# send a message to UERANSIM
def sendFuzzingMessage(msg):
    UEsocket.send(msg)
    print("send message")
    print(msg)
    return UEsocket.recv(1024).decode().strip()

# get a message from UERANSIM
def getFuzzingMessage(msg_len: int):
    return UEsocket.recv(msg_len + 1)

def execSequence(path: Path):
    if path == None:
        return True
    out_list = []
    for i in range(len(path.path_states) - 1):
        out = sendSymbol(path.input_symbols[i])
        out_list.append(out)
        time.sleep(0.1)
        if out != path.output_symbols[i]:
            print("sequence output does not match")
            print(path.input_symbols)
            print(path.output_symbols)
            print(out_list)
            return False
    return True

def check_amf():
    out = sendSymbol("registrationRequest")
    time.sleep(0.5)
    if out != "authenticationRequest":
        print("AMF Crashed")
        return True
    return False

def check_smf():
    path = Path([],[],[])
    path.input_symbols = ["registrationRequest",
                          "authenticationResponse",
                          "securityModeComplete",
                          "registrationComplete",
                          "PDUSessionEstablishmentRequest"]
    path.output_symbols = ["authenticationRequest",
                           "securityModeCommand",
                           "registrationAccept",
                           "configurationUpdateCommand",
                           "pduSessionEstablishmentAccept"]
    out_list = []
    for i in range(len(path.input_symbols) - 1):
        out = sendSymbol(path.input_symbols[i])
        out_list.append(out)
        time.sleep(0.5)
        if out != path.output_symbols[i]:
            print("SMF Crashed")
            print(path.input_symbols)
            print(path.output_symbols)
            print(out_list)
            return True
    return False

if __name__ == '__main__':
    setOffset(0)
    # load FSM
    schedule = PowerSchedule()
    if os.path.exists("./savedFSM.json") and os.path.exists("./savedFSM_sm.json"):
        fsm_file = open('./savedFSM.json', 'r')
        fsm_json = fsm_file.read()
        fsm_sm_file = open('./savedFSM_sm.json', 'r')
        fsm_sm_json = fsm_sm_file.read()
        if fsm_json != "":
            fsm = FSM.from_json(fsm_json)
            fsm.refresh_paths()
            fsm_sm = FSM.from_json(fsm_sm_json)
            fsm_sm.refresh_paths()
        else:
            fsm = load_fsm(config['FSM_PATH'])
            schedule.assignEnergy(fsm.states)
            fsm_sm = load_fsm(config['FSM_SM_PATH'])
            schedule.assignEnergy(fsm_sm.states)
        fsm_file.close()
    else:
        fsm = load_fsm(config['FSM_PATH'])
        schedule.assignEnergy(fsm.states)
        fsm_sm = load_fsm(config['FSM_SM_PATH'])
        schedule.assignEnergy(fsm_sm.states)
    atexit.register(exit_handler, fsm, fsm_sm)

    reset(True)
    full_reset = False
    
    while True:
        try:
            reset(full_reset)
            print("IMSI_OFFSET:", getOffset())
            full_reset = False
            try:
                connectUE()
            except socket.timeout:
                print("Connection timeout, retrying...")
                reset_count += 1
                if reset_count > 10:
                    full_reset = True
                    reset_count = 0
                continue
            schedule.adjustEnergy(fsm.states)
            curr_state = schedule.choose(fsm.states)
            curr_state_sm = None
            if curr_state.oracle.state == "R":
                schedule.adjustEnergy(fsm_sm.states)
            if curr_state_sm == None:
                state = curr_state.name
            else:
                state = curr_state.name + ":" + curr_state_sm.name
            print("select state", state)
            path = curr_state.select_path()
            if execSequence(path) != True:
                curr_state.count -= 1
                path.count -= 1
                reset_count += 1
                continue
            if curr_state_sm != None:
                path_sm = curr_state_sm.select_path()
                if execSequence(path_sm) != True:
                    curr_state_sm.count -= 1
                    path_sm.count -= 1
                    reset_count += 1
                    continue

            out = sendSymbol("enableFuzzing")
            print(out)
            if out == "Start fuzzing":
                print("Fuzzing enabled")
                if not curr_state.is_init:
                    for symbol in symbols_enabled:
                        msg = sendSymbol(symbol)
                        resp_json = json.loads(msg)
                        print(resp_json)
                        store_new_message(state=state,
                                        send_type=symbol,
                                        ret_type="",
                                        if_crash=False,
                                        if_crash_sm=False,
                                        is_interesting=True,
                                        if_error=False,
                                        error_cause="",
                                        sht=resp_json.get("sht"),
                                        secmod=resp_json.get("secmod"),
                                        base_msg="",
                                        new_msg=resp_json.get("new_msg"),
                                        ret_msg="",
                                        violation=False,
                                        mm_status=resp_json.get("mm_status"),
                                        byte_mut=False)
                if check_seed_msg(state):
                    curr_state.is_init = True
                else:
                    curr_state.is_init = False
                    continue
                
                fuzzing = True                                
                while fuzzing:
                    try:
                        connectGNB()
                    except socket.timeout:
                        print("Connection timeout, retrying...")
                        break
                    ins_msg = get_insteresting_msg(state)
                    if_crash=False
                    if_crash_sm=False
                    is_interesting=False
                    if_error=False
                    error_cause=""
                    print(sendSymbol("incomingMessage_"+str(ins_msg.get("size"))))
                    if ins_msg.get("send_type") == "serviceRequest":
                        sendRRCRelease()
                    try:
                        msg = sendFuzzingMessage(ins_msg.get("new_msg").encode())
                    except socket.timeout:
                        print("UE may crashed")
                        break
                    if msg == "":
                        print("UE may crashed")
                        break
                    print(msg)
                    if msg == "decode error":
                        reset_insteresting(ins_msg)
                        break
                    resp_json = json.loads(msg)
                    byte_mut = bool(resp_json.get("byte_mut"))
                    if not byte_mut:
                        is_interesting = check_new_resopnse(state, ins_msg.get("send_type"), resp_json.get("ret_msg"), resp_json.get("mm_status"))
                    if is_interesting:
                        curr_state.addEnergy(1)
                        msg_add_energy(ins_msg, 1)
                    # probe AMF
                    print("send probe to AMF")
                    startUE2()
                    time.sleep(0.1)
                    connectUE2()
                    if_crash = check_amf()
                    if if_crash:
                        fuzzing = False
                        full_reset = True
                    try:
                        msg_gnb = gNBsocket.recv(1024).decode().strip()
                        print("feedback from gnb: ", msg_gnb)
                        if "Error indication" in msg_gnb:
                            if ":" in msg_gnb:
                                error_cause = msg_gnb.split(":")[1].strip()
                            if_error = True
                            if not byte_mut:
                                is_interesting = check_new_cause(state, ins_msg.get("send_type"), error_cause)
                            if is_interesting:
                                curr_state.addEnergy(0.5)
                                msg_add_energy(ins_msg, 0.5)
                    except socket.timeout:
                        print("no feedback from gNB")
                    if resp_json.get("ret_type") != "":
                        fuzzing = False
                    violation = curr_state.oracle.query_message(ins_msg.get("send_type"), resp_json.get("ret_type"), resp_json.get("sht"), resp_json.get("secmod"))
                    print("violation: ", violation)
                    if violation:
                        violation = check_new_violation(state, ins_msg.get("send_type"), resp_json.get("ret_type"), resp_json.get("sht"), resp_json.get("secmod"))
                    # send probe to SMF
                    if ins_msg.get("send_type") in symbols_sm:
                        print("send probe to SMF")
                        startUE3()
                        time.sleep(0.1)
                        connectUE3()
                        if_crash_sm = check_smf()
                    store_new_message(state=state,
                                      send_type=ins_msg.get("send_type"),
                                      ret_type=resp_json.get("ret_type"),
                                      if_crash=if_crash,
                                      if_crash_sm=if_crash_sm,
                                      is_interesting=is_interesting,
                                      if_error=if_error,
                                      error_cause=error_cause,
                                      sht=resp_json.get("sht"),
                                      secmod=resp_json.get("secmod"),
                                      base_msg=ins_msg.get("new_msg"),
                                      new_msg=resp_json.get("new_msg"),
                                      ret_msg=resp_json.get("ret_msg"),
                                      violation=violation,
                                      mm_status=resp_json.get("mm_status"),
                                      byte_mut=byte_mut)
                    # learn new state if get a different return msg
                    if resp_json.get("ret_type") != "" and not fsm.search_new_transition(state, ins_msg.get("send_type"), resp_json.get("ret_type")) and not byte_mut:
                        print("get a different return msg")
                        message_str = ins_msg.get("send_type")+":"+resp_json.get("new_msg")+":"+str(resp_json.get("secmod"))+":"+str(resp_json.get("sht"))
                        responses = []
                        new_state_error = False
                        for symbol in symbols_fsm:
                            i = 0
                            while i < 10:
                                reset(full_reset)
                                full_reset = False
                                i = i + 1
                                try:
                                    connectGNB()
                                    connectUE()
                                except socket.timeout:
                                    print("Connection timeout, retrying...")
                                    continue
                                if not execSequence(path):
                                    print("Sequence not match, retrying...")
                                    continue
                                if sendSymbol(message_str) != resp_json.get("ret_type"):
                                    print("response to new symbol not match, retrying...")
                                    continue
                                res = sendSymbol(symbol)
                                if res == "":
                                    print("UE may crashed, retrying...")
                                    continue
                                responses.append(res)
                                break
                            if i == 10:
                                print("error in learning new state, giving up...")
                                new_state_error = True
                                break
                        if new_state_error:
                            break
                        print(responses)
                        # check if new state
                        map_state = ""
                        for s in fsm.states:
                            for i in range(len(symbols_fsm)):
                                if not fsm.search_transition(s.name, symbols_fsm[i], responses[i]):
                                    break
                                if i == len(symbols_fsm) - 1:
                                    map_state = s.name
                            if map_state != "":
                                break
                        if map_state != "":
                            new_transition = [state, message_str, resp_json.get("ret_type"), map_state]
                            fsm.transitions.append(new_transition)
                            for s in fsm.states:
                                get_all_paths(fsm, s)
                            print("new transition added")
                            print(new_transition)
                        else:
                            new_state = fsm.add_new_state()
                            new_transition = [state, message_str, resp_json.get("ret_type"), new_state.name]
                            fsm.transitions.append(new_transition)
                            # append learned input/output transitions as self loop
                            for i in range(len(symbols_fsm)):
                                new_transition = [new_state.name, symbols_fsm[i], responses[i], new_state.name]
                                fsm.transitions.append(new_transition)
                            for s in fsm.states:
                                get_all_paths(fsm, s)
                            new_state.oracle.decide_state(new_state)
                            print("new state added")
                    break
                gNBsocket.close()
                UEsocket.close()
                # save FSM after each fuzzing
                fsm_file = open('./savedFSM.json', 'w')
                fsm_file.write(fsm.to_json())
                fsm_file.close()

            else:
                print("start fuzzing error, resetting...")
        except Exception as e:
            print(e)
            error_file = open('./error.log', 'a')
            error_file.write(time.strftime("%Y-%m-%d %H:%M:%S ", time.localtime()))
            error_file.write(str(e)+"\n")
            error_file.close()
            full_reset = True
            continue