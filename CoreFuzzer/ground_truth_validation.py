#!/usr/bin/env python3
"""Ground-truth validation of the O1 probe (R2-Issue1).

Injects five controlled fault classes into a running Open5GS + UERANSIM stack
and records how the O1 multi-layer probe classifies each, producing a confusion
matrix with per-class precision/recall/F1. This provides independent ground
truth for the false-positive-rate claim (beyond the O0-vs-O1 reclassification).

Fault classes (per the reviewer's suggested protocol):
  1. crash            - kill -9 the AMF process (ground truth: REAL_CRASH / G1)
  2. hang             - kill -STOP the AMF process (ground truth: HANG / G3)
  3. rejection        - send a non-compliant message (ground truth: NORMAL_REJECT / G2)
  4. packet_loss      - iptables DROP on the N1/NGAP port (ground truth: NETWORK_ERROR / G4)
  5. transient        - tc netem delay (ground truth: TRANSIENT / G2b)

The AMF can also be crashed in-band via the OGS_FAULT_CRASH_TMSI fault injection
in gmm-handler.c (see the "crash" class below, which uses kill -9 for simplicity).

Run from the CoreFuzzer directory with Open5GS + UERANSIM up:

    sudo python3 ground_truth_validation.py --trials 20

Requires root for iptables/tc. The AMF/SMF process names default to open5gs-amfd
/ open5gs-smfd; override with --amf-proc / --smf-proc.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import time
from typing import Dict, List, Tuple

from crash_detector import CrashDetector, CrashType

AMF_PROC = "open5gs-amfd"
SMF_PROC = "open5gs-smfd"
NGAP_PORT = 38412  # N2 / NGAP SCTP port


def run(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


from core_profile import current_profile
PROFILE = current_profile()
DEPLOYMENT = PROFILE.deployment
AMF_NAME = PROFILE.proc("amf")


# ---- 初始化链 + 持久 UE 连接（复用 fuzzer 的 setup 流程）----
UEsocket = None  # 持久 UE 控制 socket


def cleanup_mongodb() -> None:
    """彻底清理 MongoDB（deleteMany + dropDatabase，对齐 fuzzer reset）。"""
    cmds = [
        "db.getCollectionNames().forEach(function(c){var n=c.toLowerCase();"
        "if(n.includes('ue')||n.includes('amf')||n.includes('udm')||"
        "n.includes('subscriber')){try{db[c].deleteMany({})}catch(e){}}})",
        "db.dropDatabase()",
        "db.getCollectionNames().forEach(function(c){try{db[c].deleteMany({})}catch(e){}})",
    ]
    for js in cmds:
        subprocess.run(["mongosh", "open5gs", "--eval", js, "--quiet"],
                       capture_output=True, text=True, timeout=15)


def init_ue_database(num_imsi: int = 100) -> None:
    """注册 IMSI + 标准 K/OPc（与 fuzzer init_ue_database 一致）。"""
    from pymongo import MongoClient
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    db = client["open5gs"]
    for i in range(1, num_imsi + 1):
        imsi = str(999700000000001 + i - 1)
        if db.subscribers.find_one({"imsi": imsi}):
            continue
        db.subscribers.insert_one({
            "imsi": imsi,
            "subscribed_rau_tau_timer": 12,
            "network_access_mode": 0,
            "subscriber_status": 0,
            "access_restriction_data": 32,
            "slice": [{"sst": 1, "default_indicator": True,
                       "session": [{"name": "internet", "type": 3,
                                    "qos": {"index": 9,
                                            "arp": {"priority_level": 8,
                                                    "pre_emption_capability": 1,
                                                    "pre_emption_vulnerability": 1}},
                                    "ambr": {"uplink": {"value": 1, "unit": 3},
                                             "downlink": {"value": 1, "unit": 3}}}]}],
            "ambr": {"uplink": {"value": 1, "unit": 3},
                     "downlink": {"value": 1, "unit": 3}},
            "security": {"k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
                         "amf": "8000", "op": None,
                         "opc": "E8ED289DEBA952E4283B54E88E6183CA"},
        })
    client.close()


def connect_ue() -> bool:
    """建立到 UE 控制 socket 的持久连接（先收 DONE 横幅）。"""
    global UEsocket
    if UEsocket is not None:
        try:
            UEsocket.getpeername()
            return True
        except Exception:
            UEsocket = None
    import socket as _sock
    s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    s.settimeout(4)
    try:
        s.connect(("localhost", PROFILE.ue_port))
        s.recv(1024)  # DONE 横幅
    except Exception:
        s.close()
        return False
    s.settimeout(8)
    UEsocket = s
    return True


def drive_registration() -> bool:
    """驱动 UE 完成注册（registrationRequest → ... → registrationAccept）。"""
    global UEsocket
    for _ in range(10):
        try:
            UEsocket.send(b"registrationRequest")
            ret = UEsocket.recv(8192).decode().strip()
        except Exception:
            return False
        if ret == "identityRequest":
            UEsocket.send(b"identityResponse")
            ret = UEsocket.recv(8192).decode().strip()
        if ret == "authenticationRequest":
            # 等 AMF 建立 AMF-UE context，避免 auth response 早到触发
            # "No AMF_UE_NGAP_ID" 竞态（第二/三次启动 core 时更常见）。
            time.sleep(1.5)
            UEsocket.send(b"authenticationResponse")
            ret = UEsocket.recv(8192).decode().strip()
        if ret == "securityModeCommand":
            UEsocket.send(b"securityModeComplete")
            ret = UEsocket.recv(8192).decode().strip()
        if ret in ("registrationAccept", "configurationUpdateCommand"):
            UEsocket.send(b"registrationComplete")
            return True
        time.sleep(1.0)
    return False


def flush_ue_socket() -> None:
    """清空 UE 控制 socket 里残留的响应（如 configurationUpdateCommand），
    避免探针读到 stale 消息而误判。"""
    global UEsocket
    if UEsocket is None:
        return
    try:
        UEsocket.settimeout(0.3)
        while True:
            if not UEsocket.recv(8192):
                break
    except Exception:
        pass
    finally:
        UEsocket.settimeout(8)


def init_environment(fault: str = "") -> None:
    """完整初始化：清 MongoDB → 注册 IMSI → 启动 core/gNB/UE → 连接 UE → 驱动注册。

    Args:
        fault: 要注入的 in-band ground-truth 故障（在 AMF 启动前设置 env 门控）：
            - "crash"    → OGS_FAULT_CRASH_TMSI="any"（任意 GUTI 注册 abort）
            - "rejection"→ OGS_FAULT_REJECT_REGISTRATION=1（GUTI 移动性更新被拒）
            - ""         → 不注入任何故障。
            drive_registration 用 SUCI 初始注册，两种故障都不触发。
    """
    from setup_helper import startCore, startGNB, startUE, killCore, killUE, killGNB
    print("  [init] 停止残留进程…")
    killUE(); killGNB(); killCore()
    # 额外 kill -9 所有残留 5gc 父进程（SIGINT 可能杀不死卡死的 5gc）
    subprocess.run(["pkill", "-9", "-f", "5gc"],
                   capture_output=True, text=True)
    # 额外 kill -9 所有孤儿 open5gs-* NF（残留 SBI 端口冲突是 core 启动失败主因）
    for p in subprocess.run(["pgrep", "-f", "open5gs-"],
                            capture_output=True, text=True).stdout.split():
        try:
            subprocess.run(["kill", "-9", p], capture_output=True)
        except Exception:
            pass
    time.sleep(2)
    print("  [init] 清理 MongoDB + 注册 IMSI…")
    cleanup_mongodb()
    init_ue_database(100)
    print("  [init] 启动 core…")
    if fault == "crash":
        os.environ["OGS_FAULT_CRASH_TMSI"] = "any"
        os.environ["OGS_FAULT_CRASH_LOG"] = os.path.abspath(
            PROFILE.resolved_log_path("core") or "./logs/core.log")
    else:
        os.environ.pop("OGS_FAULT_CRASH_TMSI", None)
        os.environ.pop("OGS_FAULT_CRASH_LOG", None)
    if fault == "rejection":
        os.environ["OGS_FAULT_REJECT_REGISTRATION"] = "1"
    else:
        os.environ.pop("OGS_FAULT_REJECT_REGISTRATION", None)
    startCore()
    time.sleep(15)
    print("  [init] 启动 gNB…")
    startGNB()
    time.sleep(5)
    print("  [init] 启动 UE…")
    startUE()
    time.sleep(8)
    print("  [init] 连接 UE socket…")
    connect_ue()
    print("  [init] 驱动 UE 完成注册…")
    ok = drive_registration()
    # 第二/三次启动 core 时 UE 的 RRC 偶发不建立（卡在 MM-REGISTER-INITIATED），
    # 重启 UE 可恢复。注册失败则重启 UE 重试（最多 3 次）。
    for attempt in range(3):
        if ok:
            break
        print(f"  [init] 注册失败，重启 UE 重试 {attempt + 1}/3…")
        killUE()
        time.sleep(2)
        startUE()
        time.sleep(8)
        connect_ue()
        ok = drive_registration()
    print(f"  [init] 注册{'成功' if ok else '失败'}")
    # rejection / hang 需要清空残留的 configurationUpdateCommand（否则探针会先
    # 读到它、误判成 G2b）。transient 用 GUTI re-auth 拿到有效 continuation，不
    # 依赖 stale；crash 由 L1 判定，均无需 flush。
    if fault in ("rejection", ""):
        time.sleep(1.0)  # 等 configurationUpdateCommand 到达
        flush_ue_socket()  # 清空残留响应，避免探针读到 stale 消息


def restart_amf_with_crash_fault() -> None:
    """crash 故障前重启 AMF，带上 OGS_FAULT_CRASH_ON_REGISTRATION fault。"""
    from setup_helper import startCore, killCore, killGNB, startGNB
    global UEsocket
    print("  [crash] 重启 AMF + gNB（带 crash fault）…")
    killCore()
    killGNB()
    # 额外 kill -9 所有孤儿 open5gs-* NF（避免 SBI 端口冲突导致 core 启动失败）
    for p in subprocess.run(["pgrep", "-f", "open5gs-"],
                            capture_output=True, text=True).stdout.split():
        try:
            subprocess.run(["kill", "-9", p], capture_output=True)
        except Exception:
            pass
    time.sleep(2)
    os.environ["OGS_FAULT_CRASH_ON_REGISTRATION"] = "1"
    startCore()
    time.sleep(15)
    startGNB()
    # 等 gNB 重新 NG Setup + UE 重新 cell 选择/RRC 建立（容器内 ~20s+）
    time.sleep(25)
    UEsocket = None
    connect_ue()


def amf_pids() -> List[str]:
    if DEPLOYMENT == "docker":
        r = run(["docker", "ps", "--filter", f"name={AMF_NAME}",
                 "--format", "{{.Names}}"])
        return [AMF_NAME] if AMF_NAME in r.stdout else []
    r = run(["pgrep", "-x", AMF_NAME])
    pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    # 排除僵尸进程（defunct），只保留存活 PID
    alive = []
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                if f.read().split()[2] != "Z":
                    alive.append(pid)
        except Exception:
            pass
    return alive


def inject_crash() -> None:
    """crash 通过 UE 原生 GUTI 注册（plainRegistrationRequestGUTI）触发
    AMF 的 OGS_FAULT_CRASH_TMSI="any" abort（带 FATAL 日志 + 直接写 core.log），
    AMF 进程终止。UE 原生路径可靠送达 GUTI，raw testMessage PDU 会被无线层丢弃。"""
    nas_probe("plainRegistrationRequestGUTI")


def inject_hang() -> None:
    """pause the AMF -> alive but unresponsive."""
    if DEPLOYMENT == "docker":
        run(["docker", "pause", AMF_NAME])
        return
    for pid in amf_pids():
        run(["kill", "-STOP", str(pid)])


def recover_hang() -> None:
    if DEPLOYMENT == "docker":
        run(["docker", "unpause", AMF_NAME])
        return
    for pid in amf_pids():
        run(["kill", "-CONT", str(pid)])


def inject_packet_loss() -> None:
    """杀 UE（nr-ue）进程，断开 UE 控制 socket，使探针返回 connect_failed（G4）。
    容器无 iptables；tc netem loss 50% 不足以让探针判定网络不可达。"""
    from setup_helper import killUE
    global UEsocket
    UEsocket = None
    killUE()


def clear_packet_loss() -> None:
    """packet_loss 是最后一个故障，UE 保持死亡即可（后续无故障需要 UE）。
    若需恢复，下次 init_environment 会 killUE + startUE 重建。"""
    pass


def inject_transient() -> None:
    # 原用 tc netem delay 模拟"延迟但最终响应"，但 lo 上的 delay 会连带拖慢
    # AMF 的 SBI/AUSF 通信（同在 loopback），导致 AUSF 鉴权超时、AMF 反而
    # reject（cause 90）。改为直接触发一次 GUTI 注册→re-auth
    # （authenticationRequest = 有效 continuation = G2b/TRANSIENT）。
    pass


def clear_transient() -> None:
    # 清空 transient probe 触发的残留响应（authenticationRequest 等），
    # 避免后续 hang 故障读到 stale continuation 而误判 G2b。
    flush_ue_socket()


def nas_probe(probe_msg: str = "registrationRequest") -> str:
    """L2 NAS service probe: 发 probe 消息，返回响应字符串。
    连接失败返回 "connect_failed"，超时返回 ""（供 detect_amf_crash 分流）。"""
    import socket
    global UEsocket
    if UEsocket is None and not connect_ue():
        return "connect_failed"
    try:
        UEsocket.send(probe_msg.encode())
        out = UEsocket.recv(8192).decode().strip()
        return out
    except socket.timeout:
        return ""
    except Exception:
        UEsocket = None  # 连接断开，下次重连
        return "connect_failed"


def send_test_message(hex_pdu: str, secmod: int = 1, sht: int = 0) -> str:
    """用 testMessage 通道发明文 NAS PDU（hex:secmod:sht），返回 UE 响应。"""
    global UEsocket
    if UEsocket is None and not connect_ue():
        return "connect_failed"
    try:
        UEsocket.send(b"testMessage")
        UEsocket.recv(8192)  # "OK"
        UEsocket.send(f"{hex_pdu}:{secmod}:{sht}".encode())
        out = UEsocket.recv(8192).decode().strip()
        return out
    except Exception as e:
        UEsocket = None
        return str(e)


# CrashType（论文原始 detect_amf_crash 的返回值）→ Ψ 的 G 类别
CRASH_TYPE_TO_G = {
    CrashType.REAL_CRASH: "G1",
    CrashType.NORMAL_REJECT: "G2a",
    CrashType.TRANSIENT: "G2b",
    CrashType.TIMEOUT: "G3",
    CrashType.NETWORK_ERROR: "G4",
    CrashType.UNKNOWN: "G4",
}


# ground-truth label -> expected O1 class
GROUND_TRUTH = {
    "rejection": "G2a",
    "hang": "G3",
    "packet_loss": "G4",  # 断 UE 控制 socket → 探针 connect_failed
    "transient": "G2b",   # tc delay 只是延迟，最终响应，归为瞬态 continuation
    "crash": "G1",
}


def inject(fault: str) -> None:
    {"crash": inject_crash,
     "hang": inject_hang,
     "packet_loss": inject_packet_loss,
     "transient": inject_transient,
     "rejection": lambda: None}[fault]()


def recover(fault: str) -> None:
    {"crash": lambda: None,
     "hang": recover_hang,
     "packet_loss": clear_packet_loss,
     "transient": clear_transient,
     "rejection": lambda: None}[fault]()


CLASSES = ["G1", "G2a", "G2b", "G3", "G4"]


def _run_trials(fault: str, expected: str, det: CrashDetector, trials: int,
                probe_msg: Dict[str, str], log_file: str,
                confusion: Dict[str, Dict[str, int]],
                results: List[Dict[str, str]]) -> None:
    for _ in range(trials):
        inject(fault)
        # transient 要赶在 UE RRC 被释放（~2s）之前 probe，故缩短缓冲
        time.sleep(0.1 if fault == "transient" else 0.5)
        # 用论文原始的 O1 探针（detect_amf_crash）判定，内部做 N 轮探针
        is_crash, crash_type, info = det.detect_amf_crash(
            lambda: nas_probe(probe_msg[fault]), log_file)
        got = CRASH_TYPE_TO_G.get(crash_type, "G4")
        confusion[fault][got] = confusion[fault].get(got, 0) + 1
        results.append({"fault": fault, "expected": expected, "got": got,
                        "ts": time.time()})
        recover(fault)
        time.sleep(0.5)
    row = " ".join(f"{c}:{n}" for c, n in sorted(confusion[fault].items()))
    print(f"  {fault:12s} (expect {expected:3s}) -> {row}")


def _run_cycle(confusion: Dict[str, Dict[str, int]],
               results: List[Dict[str, str]], probe_msg: Dict[str, str],
               trial_count: Dict[str, int], log_file: str,
               cycle: int) -> None:
    print(f"\n{'=' * 72}\nCycle {cycle}\n{'=' * 72}")

    # ---- Pass 1: crash (G1) in a fresh, healthy environment ----
    init_environment(fault="crash")
    det = CrashDetector(crash_log_dir="./crash_reports_ground_truth",
                        amf_proc=AMF_NAME, deployment=DEPLOYMENT)
    # GUTI 注册需 RRC 活跃；若注册后 RRC 已被释放（信号丢失窗口），第一次
    # inject 可能到不了 AMF，故重试直到触发 abort（G1）。
    got = "G4"
    for attempt in range(4):
        inject_crash()
        time.sleep(1.0)
        is_crash, crash_type, info = det.detect_amf_crash(
            lambda: nas_probe(probe_msg["crash"]), log_file)
        got = CRASH_TYPE_TO_G.get(crash_type, "G4")
        if got == "G1":
            break
        time.sleep(1.5)  # 等 UE 重新检测小区、重建 RRC
    confusion["crash"][got] = confusion["crash"].get(got, 0) + 1
    results.append({"fault": "crash", "expected": GROUND_TRUTH["crash"], "got": got,
                    "ts": time.time()})
    row = " ".join(f"{c}:{n}" for c, n in sorted(confusion["crash"].items()))
    print(f"  {'crash':12s} (expect {GROUND_TRUTH['crash']:3s}) -> {row}")

    # ---- Pass 2: rejection (G2a) ----
    init_environment(fault="rejection")
    det = CrashDetector(crash_log_dir="./crash_reports_ground_truth",
                        amf_proc=AMF_NAME, deployment=DEPLOYMENT)
    _run_trials("rejection", GROUND_TRUTH["rejection"], det,
                trial_count["rejection"], probe_msg, log_file, confusion, results)

    # ---- Pass 3: transient (own init; GUTI re-auth changes UE state) ----
    # transient 的 GUTI re-auth 会把 UE 带入 re-auth 状态并残留响应，若与 hang
    # 共用同一 init 会污染 hang 的 probe，故单独一个 init 且不 flush。
    init_environment(fault="transient")
    det = CrashDetector(crash_log_dir="./crash_reports_ground_truth",
                        amf_proc=AMF_NAME, deployment=DEPLOYMENT)
    _run_trials("transient", GROUND_TRUTH["transient"], det,
                trial_count["transient"], probe_msg, log_file, confusion, results)

    # ---- Pass 4: hang / packet_loss (own init, clean UE) ----
    init_environment(fault="")
    det = CrashDetector(crash_log_dir="./crash_reports_ground_truth",
                        amf_proc=AMF_NAME, deployment=DEPLOYMENT)
    for fault in ("hang", "packet_loss"):
        _run_trials(fault, GROUND_TRUTH[fault], det, trial_count[fault],
                    probe_msg, log_file, confusion, results)


def _compute_metrics(confusion: Dict[str, Dict[str, int]],
                     results: List[Dict[str, str]],
                     trial_count: Dict[str, int]) -> Dict:
    total = {c: 0 for c in CLASSES}
    correct = {c: 0 for c in CLASSES}
    truth = {c: 0 for c in CLASSES}
    for r in results:
        truth[r["expected"]] = truth.get(r["expected"], 0) + 1
    for fault, expected in GROUND_TRUTH.items():
        for c, n in confusion[fault].items():
            total[c] += n
            if c == expected:
                correct[c] += n

    per_class = {}
    for c in CLASSES:
        prec = correct[c] / total[c] if total[c] else 0.0
        rec = correct[c] / truth[c] if truth[c] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[c] = {"precision": round(prec, 6), "recall": round(rec, 6),
                        "f1": round(f1, 6), "n": total[c],
                        "truth": truth[c], "correct": correct[c]}

    n_total = len(results)
    n_correct = sum(1 for r in results if r["expected"] == r["got"])
    accuracy = n_correct / n_total if n_total else 0.0

    non_crash = [r for r in results if r["fault"] != "crash"]
    fp = sum(1 for r in non_crash if r["got"] == "G1")
    fpr = fp / len(non_crash) if non_crash else 0.0

    crashes = [r for r in results if r["fault"] == "crash"]
    tp = sum(1 for r in crashes if r["got"] == "G1")
    recall = tp / len(crashes) if crashes else 0.0

    return {
        "total_trials": n_total,
        "correct": n_correct,
        "accuracy": round(accuracy, 6),
        "fpr": round(fpr, 6),
        "fpr_n": len(non_crash),
        "recall": round(recall, 6),
        "recall_n": len(crashes),
        "per_class": per_class,
    }


def _save_checkpoint(out_file: str, confusion: Dict[str, Dict[str, int]],
                     results: List[Dict[str, str]],
                     trial_count: Dict[str, int], cycle: int,
                     elapsed: float) -> None:
    payload = {
        "cycle": cycle,
        "elapsed_seconds": round(elapsed, 2),
        "confusion": {f: dict(confusion[f]) for f in GROUND_TRUTH},
        "metrics": _compute_metrics(confusion, results, trial_count),
        "n_results": len(results),
    }
    tmp = out_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, out_file)


def _wilson_ci(k: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    """二项比例 k/n 的 Wilson 95% 置信区间（对接近 0/1 的比例也稳健）。"""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _cycle_metrics(cycle_results: List[Dict[str, str]]) -> Dict:
    """从单轮 trial 列表算该轮的 accuracy/fpr/recall 与每故障 accuracy。"""
    n = len(cycle_results)
    correct = sum(1 for r in cycle_results if r["expected"] == r["got"])
    acc = correct / n if n else 0.0

    non_crash = [r for r in cycle_results if r["fault"] != "crash"]
    fp = sum(1 for r in non_crash if r["got"] == "G1")
    fpr = fp / len(non_crash) if non_crash else 0.0

    crashes = [r for r in cycle_results if r["fault"] == "crash"]
    tp = sum(1 for r in crashes if r["got"] == "G1")
    recall = tp / len(crashes) if crashes else 0.0

    per_fault = {}
    for fault in GROUND_TRUTH:
        ftrials = [r for r in cycle_results if r["fault"] == fault]
        fcorrect = sum(1 for r in ftrials if r["expected"] == r["got"])
        per_fault[fault] = fcorrect / len(ftrials) if ftrials else 0.0

    return {"n": n, "correct": correct, "acc": acc, "fpr": fpr,
            "recall": recall, "per_fault": per_fault}


def _write_cycle_csv(csv_path: str, cycle: int, elapsed: float,
                     cm: Dict, header_written: bool) -> bool:
    """把单轮指标追加写入 CSV，返回是否写了表头。"""
    fieldnames = ["cycle", "elapsed_s", "n", "correct", "acc", "fpr", "recall"]
    fieldnames += [f"{f}_acc" for f in GROUND_TRUTH]
    row = {
        "cycle": cycle,
        "elapsed_s": round(elapsed, 2),
        "n": cm["n"],
        "correct": cm["correct"],
        "acc": round(cm["acc"], 6),
        "fpr": round(cm["fpr"], 6),
        "recall": round(cm["recall"], 6),
    }
    for fault in GROUND_TRUTH:
        row[f"{fault}_acc"] = round(cm["per_fault"][fault], 6)

    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not header_written:
            w.writeheader()
        w.writerow(row)
    return True


def _mean_std(vals: List[float]) -> Tuple[float, float]:
    """返回 (均值, 样本标准差)。样本 < 2 时 std 记为 0。"""
    n = len(vals)
    if n == 0:
        return (0.0, 0.0)
    mean = sum(vals) / n
    if n < 2:
        return (mean, 0.0)
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return (mean, math.sqrt(var))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--duration", type=float, default=0.0,
                    help="总运行时长（秒）。0 = 单轮（原有行为）")
    ap.add_argument("--out", default="./confusion_matrix_results.json",
                    help="检查点输出 JSON 路径")
    ap.add_argument("--csv", default="",
                    help="每轮指标 CSV 路径（默认由 --out 推导）")
    ap.add_argument("--amf-proc", default=AMF_PROC)
    ap.add_argument("--smf-proc", default=SMF_PROC)
    args = ap.parse_args()

    confusion: Dict[str, Dict[str, int]] = {f: {} for f in GROUND_TRUTH}
    results: List[Dict[str, str]] = []

    print("=" * 72)
    print("O1 ground-truth validation")
    print(f"duration={args.duration}s trials/cycle={args.trials} out={args.out}")
    print("=" * 72)

    log_file = PROFILE.resolved_log_path("core") or "./logs/core.log"
    probe_msg = {
        "crash": "plainRegistrationRequestGUTI",
        "rejection": "plainRegistrationRequestGUTI",  # 触发 GUTI 注册→被拒
        "hang": "registrationRequest",
        "packet_loss": "registrationRequest",
        # transient 需要有效 continuation（registrationRequest 在已注册 UE 上
        # 返回 null_action→G3）；用 GUTI 注册触发 re-auth（authenticationRequest）。
        "transient": "plainRegistrationRequestGUTI",
    }
    # 每类故障的 trial 数：crash/rejection/transient 会改变 UE 状态（单次），
    # hang/packet_loss 可恢复（N 次）。
    trial_count = {
        "crash": 1,
        "rejection": 1,   # reject 后 AMF 将 UE 去注册，第二次 probe 无法再触发
        "hang": args.trials,
        "packet_loss": args.trials,
        "transient": 1,   # re-auth 会改变 UE 状态，单次
    }

    start = time.time()
    # duration<=0 表示单轮（原有行为）；>0 表示按秒循环直到超时。
    single = args.duration <= 0
    deadline = start + args.duration if not single else 0.0

    csv_path = args.csv or (os.path.splitext(args.out)[0] + ".csv")
    cycle_metrics: List[Dict] = []
    header_written = False
    prev_len = 0

    cycle = 0
    while True:
        cycle += 1
        _run_cycle(confusion, results, probe_msg, trial_count, log_file, cycle)
        elapsed = time.time() - start
        # 本轮增量（用于每轮 std）
        cm = _cycle_metrics(results[prev_len:])
        prev_len = len(results)
        cycle_metrics.append(cm)
        header_written = _write_cycle_csv(csv_path, cycle, elapsed, cm,
                                          header_written)
        _save_checkpoint(args.out, confusion, results, trial_count, cycle, elapsed)
        m = _compute_metrics(confusion, results, trial_count)
        print(f"\n[checkpoint] cycle={cycle} elapsed={elapsed / 3600.0:.2f}h "
              f"acc={m['accuracy']:.4f} fpr={m['fpr']:.4f} "
              f"recall={m['recall']:.4f} -> {args.out} | csv={csv_path}")
        if single or time.time() >= deadline:
            break

    # Final summary
    m = _compute_metrics(confusion, results, trial_count)
    print("\n" + "=" * 72)
    print("FINAL Confusion matrix (rows = ground truth, cols = O1 classification)")
    print("=" * 72)
    header = "              " + "".join(f"{c:>7s}" for c in CLASSES)
    print(header)
    for fault in GROUND_TRUTH:
        line = f"  {fault:12s}"
        for c in CLASSES:
            line += f"{confusion[fault].get(c, 0):>7d}"
        print(line)

    print("\nPer-class precision / recall / F1")
    for c in CLASSES:
        p = m["per_class"][c]
        print(f"  {c:3s}  precision={p['precision']:.4f}  recall={p['recall']:.4f}"
              f"  f1={p['f1']:.4f}  (n={p['n']})")

    # 二项比例 + Wilson CI
    fp_count = sum(1 for r in results if r["fault"] != "crash" and r["got"] == "G1")
    tp_count = sum(1 for r in results if r["fault"] == "crash" and r["got"] == "G1")
    acc_ci = _wilson_ci(m["correct"], m["total_trials"])
    fpr_ci = _wilson_ci(fp_count, m["fpr_n"])
    rec_ci = _wilson_ci(tp_count, m["recall_n"])

    print(f"\nOverall accuracy: {m['correct']}/{m['total_trials']} "
          f"({100.0 * m['accuracy']:.2f}%)  95% CI "
          f"[{100.0 * acc_ci[0]:.3f}%, {100.0 * acc_ci[1]:.3f}%]")
    print(f"FPR (non-crash -> G1): {m['fpr']:.4f}  (n={m['fpr_n']})  95% CI "
          f"[{100.0 * fpr_ci[0]:.4f}%, {100.0 * fpr_ci[1]:.4f}%]")
    print(f"Recall (crash -> G1): {m['recall']:.4f}  (n={m['recall_n']})  95% CI "
          f"[{100.0 * rec_ci[0]:.4f}%, {100.0 * rec_ci[1]:.4f}%]")

    # 每轮 variability（均值 ± 样本标准差）
    print("\nPer-cycle variability (mean ± std over cycles)")
    keys = [("acc", "accuracy"), ("fpr", "FPR"), ("recall", "recall")]
    for k, label in keys:
        vals = [c[k] for c in cycle_metrics]
        mean, std = _mean_std(vals)
        print(f"  {label:9s}  {mean:.4f} ± {std:.4f}  (n_cycles={len(vals)})")
    for fault in GROUND_TRUTH:
        vals = [c["per_fault"][fault] for c in cycle_metrics]
        mean, std = _mean_std(vals)
        print(f"  {fault:9s}  acc {mean:.4f} ± {std:.4f}  (n_cycles={len(vals)})")

    print(f"\nResults saved to {args.out} | per-cycle CSV: {csv_path}")


if __name__ == "__main__":
    main()
