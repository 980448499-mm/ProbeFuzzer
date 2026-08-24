#!/usr/bin/env python3
"""Online replay of Φ candidates against live Open5GS + UERANSIM."""
from __future__ import annotations

import csv
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from objects.oracle import Oracle  # noqa: E402

CSV_IN = ROOT / "phi_violations_13_20251209_233953.csv"
OUT_CSV = ROOT / "phi_violations_13_online_replay.csv"
OUT_JSON = ROOT / "phi_violations_13_online_replay.json"
UE_HOST, UE_PORT = "127.0.0.1", 45678
UE_CFG = os.environ.get("UE_CFG", "/corefuzzer_deps/ueransim/config/open5gs-ue.yaml")
UE_IMSI = os.environ.get("UE_IMSI", "imsi-999700000000001")
UE_LOG = ROOT / "logs" / "ue_replay.log"
FIELDS = [
    "id", "send_type", "orig_ret", "sht", "secmod", "byte_mut", "new_msg",
    "prefix_ret", "replay_A_recorded_meta", "replay_B_wire_plain",
    "phi_orig_on_recorded", "phi_on_wire_params", "online_verdict", "notes",
]


def sh(cmd: str) -> None:
    subprocess.run(cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_ue() -> None:
    # Avoid pkill -f self-match; kill by exact binary name
    out = subprocess.run(["pgrep", "-x", "nr-ue"], capture_output=True, text=True)
    for pid in out.stdout.split():
        try:
            os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass
    time.sleep(0.5)


def wait_port(port: int, timeout: float = 15.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect((UE_HOST, port))
            s.close()
            return True
        except Exception:
            time.sleep(0.2)
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


def start_ue() -> None:
    UE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(UE_LOG, "a") as out:
        out.write(f"\n=== UE restart {time.strftime('%F %T')} ===\n")
        subprocess.Popen(
            ["nr-ue", "-c", UE_CFG, "-i", UE_IMSI],
            stdout=out,
            stderr=out,
            start_new_session=True,
        )
    if not wait_port(UE_PORT, 20):
        raise RuntimeError("UE control port not ready")
    # Let auto initial registration settle / fail without holding our socket
    time.sleep(2.0)


def recv_line(sock: socket.socket, timeout: float = 8.0) -> str:
    sock.settimeout(timeout)
    data = sock.recv(8192)
    if not data:
        return ""
    return data.decode(errors="replace").strip()


def connect_ue(timeout: float = 5.0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((UE_HOST, UE_PORT))
    # banner / DONE
    try:
        recv_line(s, timeout=3.0)
    except Exception:
        pass
    return s


def send_cmd(sock: socket.socket, cmd: str, timeout: float = 8.0) -> str:
    sock.send(cmd.encode())
    return recv_line(sock, timeout=timeout)


def replay_test_message(sock: socket.socket, hex_pdu: str, secmod: int, sht: int, timeout: float = 8.0) -> str:
    ok = send_cmd(sock, "testMessage", timeout=5.0)
    if "OK" not in ok.upper():
        return f"TESTMSG_HANDSHAKE_FAIL:{ok}"
    payload = f"{hex_pdu}:{secmod}:{sht}"
    sock.send(payload.encode())
    return recv_line(sock, timeout=timeout) or "TIMEOUT_OR_EMPTY"


def is_msg_name(x: str) -> bool:
    if not x:
        return False
    if x.startswith(("ERR", "TESTMSG_", "TIMEOUT")):
        return False
    if x == "null_action":
        return True
    return x[0].islower() and " " not in x and ":" not in x


def fresh_ue_socket() -> socket.socket:
    kill_ue()
    start_ue()
    return connect_ue()


def main() -> int:
    rows = list(csv.DictReader(CSV_IN.open(encoding="utf-8-sig")))
    results = []

    print("=== Env smoke: restart UE and register ===")
    try:
        sock = fresh_ue_socket()
        smoke = send_cmd(sock, "registrationRequest", timeout=12.0)
        print(f"smoke registrationRequest -> {smoke}")
        sock.close()
    except Exception as e:
        print(f"FATAL smoke failed: {e}")
        return 1

    for row in rows:
        cid = row["id"]
        send_type = row["send_type_inferred"]
        orig_ret = row["ret_type"]
        sht = int(row["sht"])
        secmod = int(row["secmod"])
        byte_mut = row.get("byte_mut", "")
        new_msg = row["new_msg"].strip()
        print(f"\n===== Case #{cid} {send_type} -> {orig_ret} (sht={sht}, secmod={secmod}) =====")

        prefix_ret = ""
        ret_a = ""
        ret_b = ""
        notes = []

        # ---- Mode A: recorded sht/secmod ----
        try:
            sock = fresh_ue_socket()
            if send_type in ("authenticationResponse", "authenticationFailure", "identityResponse"):
                prefix_ret = send_cmd(sock, "registrationRequest", timeout=12.0)
                print(f"  prefix -> {prefix_ret}")
                time.sleep(0.4)
            ret_a = replay_test_message(sock, new_msg, secmod, sht, timeout=10.0)
            sock.close()
        except Exception as e:
            ret_a = f"ERR:{e}"
            notes.append(f"A_err:{e}")
        print(f"  A recorded meta  -> {ret_a}")

        # ---- Mode B: wire-faithful plaintext ----
        try:
            sock = fresh_ue_socket()
            if send_type in ("authenticationResponse", "authenticationFailure", "identityResponse"):
                pr = send_cmd(sock, "registrationRequest", timeout=12.0)
                if not prefix_ret:
                    prefix_ret = pr
                time.sleep(0.4)
            ret_b = replay_test_message(sock, new_msg, 1, 0, timeout=10.0)
            sock.close()
        except Exception as e:
            ret_b = f"ERR:{e}"
            notes.append(f"B_err:{e}")
        print(f"  B wire plaintext -> {ret_b}")

        oracle = Oracle()
        phi_orig = bool(oracle.query_message(send_type, orig_ret, sht, secmod))
        if is_msg_name(ret_b) and ret_b != "null_action":
            phi_wire = bool(oracle.query_message(send_type, ret_b, 0, 1))
        else:
            phi_wire = False

        # Verdict policy for "real CN protocol violation"
        if ret_a == "null_action" and secmod > 1:
            online = "NOT_REAL_SECMOD_BLOCKS_SEND"
            notes.append("recorded secmod>1 without security context => PDU not sent")
        elif is_msg_name(ret_b) and ret_b != "null_action":
            if phi_orig and not phi_wire:
                online = "NOT_REAL_CN_VIOLATION_PHI_METADATA_FP"
                notes.append("wire-faithful plaintext does not fail Φ; original Φ from sht/secmod metadata")
            elif phi_wire:
                online = "CANDIDATE_NEEDS_CLAUSE_CHECK"
                notes.append("Φ still true with wire params; need TS24.501 clause mapping")
            else:
                online = "NOT_REAL_CN_VIOLATION_NORMAL_RESPONSE"
                notes.append("network response is expected under plaintext replay")
        elif is_msg_name(ret_a) and ret_a != "null_action":
            if ret_a == orig_ret and phi_orig:
                online = "REPRODUCED_PHI_BUT_LIKELY_METADATA"
                notes.append("recorded-meta replay matched original ret; still likely metadata FP")
            else:
                online = "INCONCLUSIVE_PARTIAL"
        else:
            online = "INCONCLUSIVE_REPLAY"
            notes.append("could not obtain typed NAS response on replay")

        rec = {
            "id": cid,
            "send_type": send_type,
            "orig_ret": orig_ret,
            "sht": sht,
            "secmod": secmod,
            "byte_mut": byte_mut,
            "new_msg": new_msg,
            "prefix_ret": prefix_ret,
            "replay_A_recorded_meta": ret_a,
            "replay_B_wire_plain": ret_b,
            "phi_orig_on_recorded": phi_orig,
            "phi_on_wire_params": phi_wire,
            "online_verdict": online,
            "notes": "; ".join(notes),
        }
        results.append(rec)
        print(f"  verdict: {online} | phi_orig={phi_orig} phi_wire={phi_wire}")

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for k, v in Counter(r["online_verdict"] for r in results).items():
        print(f"  {k}: {v}")
    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_JSON}")

    # leave one UE running
    try:
        fresh_ue_socket().close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
