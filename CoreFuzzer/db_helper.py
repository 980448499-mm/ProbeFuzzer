from pymongo.mongo_client import MongoClient
from dotenv import dotenv_values
from objects import Seed, PowerSchedule
import time

config = dotenv_values(".env")

# Replace the placeholder with your Atlas connection string
uri = config["MONGO_URI"]
# Set the Stable API version when creating a new client
client = MongoClient(uri)

col = client["CoreFuzzer"][config["DB_NAME"]]
col.create_index([("state"), ("new_msg"), ("sht"), ("secmod")], unique=True)
col.create_index([("is_interesting"), ("mutate_count", 1)])

def store_new_message(state: str, send_type: str, ret_type: str, if_crash: bool, if_crash_sm: bool, is_interesting: bool, if_error: bool, error_cause: str, sht: int, secmod: int, base_msg: str, new_msg: str, ret_msg: str, violation: bool, mm_status: str, byte_mut: bool):
    try:
        col.insert_one({
            "timestamp": time.time(),
            "state": state,
            "send_type": send_type,
            "ret_type": ret_type,
            "if_crash": if_crash,
            "if_crash_sm": if_crash_sm,
            "if_error": if_error,
            "error_cause": error_cause,
            "is_interesting": is_interesting,
            "sht": sht,
            "secmod": secmod,
            "size": len(new_msg),
            "base_msg": base_msg,
            "new_msg": new_msg,
            "ret_msg": ret_msg,
            "energy": 1.0,
            "mutate_count": 0,
            "violation": violation,
            "mm_status": mm_status,
            "byte_mut": byte_mut
            })
    except Exception as e:
        # print(e)
        print("Duplicated message!")

def check_seed_msg(state: str):
    msg_count = col.count_documents(filter={"state": state, "is_interesting": True})
    if msg_count >= 1:
        return True
    else:
        return False

def get_insteresting_msg(state: str):
    msg_list = col.find(filter={"state": state, "is_interesting": True})
    msgs = []
    for msg in msg_list:
        msgs.append(BaseMsg(msg.get("_id"), msg.get("mutate_count"), msg.get("energy")))
    if not msgs:
        return None
    ps = PowerSchedule()
    ps.adjustEnergy(msgs)
    seed = ps.choose(msgs)
    return col.find_one_and_update(filter={"_id": seed.id},
                                   update={"$inc": {"mutate_count": 1}})

def get_msg_by_id(id: str):
    return col.find_one(filter={"_id": id})
    
def msg_add_energy(msg, energy):
    col.update_one(filter={"_id": msg["_id"]},
                   update={"$inc": {"energy": energy}})

def reset_insteresting(msg):
    col.update_one(filter={"_id": msg["_id"]},
                   update={"$set": {"is_interesting": False}})

def check_new_resopnse(state: str, send_type: str, ret_msg: str, mm_status: str):
    if "7E0056" in ret_msg: # exclude duplicated authentication request
        if col.find_one(filter={"state": state, "send_type": send_type, "ret_type": "authenticationRequest"}) != None:
            return False
        else:
            return True
    else:
        if col.find_one(filter={"state": state, "send_type": send_type, "ret_msg": ret_msg, "mm_status": mm_status}) != None:
            return False
        else:
            return True

def check_new_cause(state: str, send_type: str, error_cause: str):
    if col.find_one(filter={"state": state, "send_type": send_type, "error_cause": error_cause}) != None:
        return False
    else:
        return True

# if the violation is unique, return True
def check_new_violation(state: str, send_type: str, ret_type: str, sht: int, secmod: int):
    if col.find_one(filter={"violation": True, "state": state, 
                            "send_type": send_type, "ret_type": ret_type,
                            "sht": sht, "secmod": secmod}) != None:
        return False
    else:
        return True
    
class BaseMsg(Seed):
    def __init__(self, id: str, count: int, energy: float):
        super().__init__()
        self.id = id
        self.count = count
        self.energy = energy
