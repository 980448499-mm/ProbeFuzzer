#!/usr/bin/env python3
"""Open5GS vs free5GC consistency replay for AMF+SMF wire-Φ hits."""
from __future__ import annotations

import csv
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from objects.oracle import component_for_send_type, query_component_violation  # noqa: E402
from objects.oracle_amf import OracleAmf  # noqa: E402
from objects.oracle_smf import OracleSmf  # noqa: E402
from objects.pv_probes import semantic_divergence  # noqa: E402

OUT = ROOT / "consistency_compare_results.json"
UE_PORT = 45678

OPEN5GS_GNB = os.environ.get("OPEN5GS_GNB", "/corefuzzer_deps/ueransim/config/open5gs-gnb.yaml")
OPEN5GS_UE = os.environ.get("OPEN5GS_UE", "/corefuzzer_deps/ueransim/config/open5gs-ue.yaml")
OPEN5GS_IMSI = os.environ.get("OPEN5GS_IMSI", "imsi-999700000000001")
F5GC_GNB = ROOT / "config" / "free5gc-gnb-host.yaml"
F5GC_UE = ROOT / "config" / "free5gc-ue.yaml"
if not F5GC_UE.exists():
    F5GC_UE = ROOT / "config" / "free5gc-ue-host.yaml"
F5GC_IMSI = "imsi-208930000000001"

SM_SYMBOLS = {
    "PDUSessionEstablishmentRequest",
    "PDUSessionAuthenticationComplete",
    "PDUSessionModificationRequest",
    "PDUSessionModificationComplete",
    "PDUSessionModificationCommandReject",
    "PDUSessionReleaseRequest",
    "PDUSessionReleaseComplete",
    "gsmStatus",
    "ulNasTransport",
}


def sh(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)


def kill_procs(*names: str) -> None:
    for n in names:
        out = subprocess.run(["pgrep", "-x", n], capture_output=True, text=True)
        for pid in out.stdout.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    time.sleep(0.5)


def wait_port(port: int, timeout: float = 20) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
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


def recv_line(sock: socket.socket, timeout: float = 10) -> str:
    sock.settimeout(timeout)
    data = sock.recv(8192)
    return data.decode(errors="replace").strip() if data else ""


def connect_ue() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(("127.0.0.1", UE_PORT))
    try:
        recv_line(s, 3)
    except Exception:
        pass
    return s


def send_cmd(sock: socket.socket, cmd: str, timeout: float = 10) -> str:
    sock.send(cmd.encode())
    return recv_line(sock, timeout)


def replay_test_message(sock: socket.socket, hex_pdu: str, secmod: int, sht: int, timeout: float = 12) -> str:
    ok = send_cmd(sock, "testMessage", timeout=5)
    if "OK" not in ok.upper():
        return f"HANDSHAKE_FAIL:{ok}"
    sock.send(f"{hex_pdu}:{secmod}:{sht}".encode())
    return recv_line(sock, timeout) or "TIMEOUT"


def replay_with_prefixes(sock: socket.socket, hex_pdu: str, secmod: int, sht: int, prefixes: list[str]) -> str:
    for step in prefixes:
        ret = send_cmd(sock, step, timeout=15)
        if ret.startswith(("ERR", "HANDSHAKE")):
            return f"PREFIX_FAIL:{step}:{ret}"
        time.sleep(0.35)
    return replay_test_message(sock, hex_pdu, secmod, sht)


def prefix_plan(send_type: str, component: str) -> list[str]:
    if component == "smf" or send_type in SM_SYMBOLS:
        return [
            "registrationRequest",
            "authenticationResponse",
            "securityModeComplete",
            "registrationComplete",
            "PDUSessionEstablishmentRequest",
        ]
    if send_type in ("authenticationResponse", "authenticationFailure"):
        return ["registrationRequest"]
    if send_type == "identityResponse":
        return [
            "registrationRequest",
            "authenticationResponse",
            "securityModeComplete",
        ]
    if send_type == "securityModeComplete":
        return ["registrationRequest", "authenticationResponse"]
    if send_type == "registrationComplete":
        return [
            "registrationRequest",
            "authenticationResponse",
            "securityModeComplete",
        ]
    if send_type == "registrationRequest":
        return []
    return []


def load_hits() -> list[dict]:
    rows: list[dict] = []
    seen = set()
    max_rows = int(os.environ.get("DIFF_MAX_ROWS", "40"))
    files = (
        "wire_phi_hits_amf.csv",
        "wire_phi_hits_smf.csv",
        "wire_phi_hits.csv",
        "typed_responses.csv",
    )
    for name in files:
        path = ROOT / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        with path.open(encoding="utf-8-sig") as f:
            first = f.readline()
            if not first.strip() or "send_type" not in first:
                continue
            f.seek(0)
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("send_type") or not row.get("new_msg") or not row.get("ret_type"):
                    continue
                key = (row.get("send_type"), row.get("ret_type"), (row.get("new_msg") or "")[:48])
                if key in seen:
                    continue
                seen.add(key)
                if "component" not in row or not row["component"]:
                    row["component"] = component_for_send_type(row.get("send_type", ""))
                rows.append(row)
    # Prefer continuation / bypass rows, then cap replay cost
    def _rank(r: dict) -> tuple:
        kind = r.get("kind") or ""
        ret = r.get("ret_type") or ""
        bypass = 0 if str(kind).startswith("plain_") else 1
        cont = 0 if ret.endswith("Accept") or ret.endswith("Command") or ret.endswith("Request") else 1
        return (bypass, cont)

    rows.sort(key=_rank)
    if len(rows) > max_rows:
        print(f"differential cap: using {max_rows}/{len(rows)} typed rows (DIFF_MAX_ROWS)")
        rows = rows[:max_rows]
    return rows


def start_open5gs_stack() -> None:
    kill_procs("nr-ue", "nr-gnb")
    if not subprocess.run(["pgrep", "-x", "open5gs-amfd"], capture_output=True).stdout.strip():
        sh("nohup 5gc -c /corefuzzer_deps/open5gs/build/configs/sample.yaml >> /corefuzzer/logs/o5gs_cmp.log 2>&1 &")
        time.sleep(6)
    sh(f"nohup nr-gnb -c {OPEN5GS_GNB} >> /corefuzzer/logs/gnb_o5gs_cmp.log 2>&1 &")
    time.sleep(3)
    sh(f"nohup nr-ue -c {OPEN5GS_UE} -i {OPEN5GS_IMSI} >> /corefuzzer/logs/ue_o5gs_cmp.log 2>&1 &")
    if not wait_port(UE_PORT, 25):
        raise RuntimeError("Open5GS UE control port not ready")


def start_free5gc_stack() -> None:
    kill_procs("nr-ue", "nr-gnb", "open5gs-amfd")
    for n in ["open5gs-smfd", "open5gs-upfd", "open5gs-nrfd"]:
        out = subprocess.run(["pgrep", "-x", n], capture_output=True, text=True)
        for pid in out.stdout.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    time.sleep(1)
    if not sh("ss -ln | grep -q ':38413'").returncode == 0:
        raise RuntimeError("free5GC AMF not listening on host :38413")
    sh(f"nohup nr-gnb -c {F5GC_GNB} >> /corefuzzer/logs/gnb_f5gc_cmp.log 2>&1 &")
    time.sleep(3)
    sh(f"nohup nr-ue -c {F5GC_UE} -i {F5GC_IMSI} >> /corefuzzer/logs/ue_f5gc_cmp.log 2>&1 &")
    if not wait_port(UE_PORT, 25):
        raise RuntimeError("free5GC UE control port not ready")


def clause_note(component: str, send_type: str, ret_type: str, wire_sht: int) -> str:
    if component == "smf":
        if send_type == "PDUSessionEstablishmentRequest" and ret_type == "pduSessionEstablishmentAccept":
            return "TS24.501/29.502: 未注册或会话状态不匹配时仍 Accept 属 SMF 侧可疑续办"
        if ret_type == "pduSessionModificationCommand":
            return "TS24.501: 无有效 PDU 会话时下发 Modification Command 需核查"
        return "SMF: 对照 PDU session FSM 与 TS 24.501 5GSM"
    if send_type == "identityResponse" and ret_type == "authenticationRequest":
        return "TS24.501: identityResponse 后进入鉴权通常合法；需 MM 状态对齐"
    if send_type == "registrationRequest" and ret_type == "authenticationRequest" and wire_sht == 1:
        return "TS24.501: 初始注册期望明文 Registration Request(SHT=0)"
    return "AMF: 对照 MM 状态机与 NAS 安全头"


def main() -> int:
    rows = load_hits()
    if not rows:
        print("no typed responses or wire-Φ hits found")
        return 1

    amf_oracle = OracleAmf()
    smf_oracle = OracleSmf()
    results = []

    for row in rows:
        send_type = row["send_type"]
        component = row.get("component") or component_for_send_type(send_type)
        new_msg = row["new_msg"]
        sht = int(row["sht"])
        secmod = int(row["secmod"])
        wire_sht, wire_sec, meta = normalize_wire_security(new_msg, sht, secmod)
        prefixes = prefix_plan(send_type, component)

        rec = {
            "iteration": row.get("iteration"),
            "component": component,
            "send_type": send_type,
            "orig_ret": row["ret_type"],
            "wire_sht": wire_sht,
            "wire_secmod": wire_sec,
            "prefix_steps": prefixes,
            "open5gs_ret": "ERR",
            "free5gc_ret": "ERR",
            "confirmed_inconsistency": False,
            "semantic_divergence": False,
            "confirmed_pv": False,
            "clause_note": clause_note(component, send_type, row["ret_type"], wire_sht),
            "meta": meta,
        }

        try:
            kill_procs("nr-ue", "nr-gnb")
            start_open5gs_stack()
            sock = connect_ue()
            rec["open5gs_ret"] = replay_with_prefixes(sock, new_msg, wire_sec, wire_sht, prefixes)
            sock.close()
        except Exception as e:
            rec["open5gs_ret"] = f"ERR:{e}"

        try:
            kill_procs("nr-ue", "nr-gnb")
            start_free5gc_stack()
            sock = connect_ue()
            rec["free5gc_ret"] = replay_with_prefixes(sock, new_msg, wire_sec, wire_sht, prefixes)
            sock.close()
        except Exception as e:
            rec["free5gc_ret"] = f"ERR:{e}"

        o, f = rec["open5gs_ret"], rec["free5gc_ret"]
        rec["replay_ok"] = (
            o[:1].islower()
            and f[:1].islower()
            and not o.startswith(("HANDSHAKE_FAIL", "PREFIX_FAIL", "ERR", "TIMEOUT"))
            and not f.startswith(("HANDSHAKE_FAIL", "PREFIX_FAIL", "ERR", "TIMEOUT"))
        )
        if (
            o[:1].islower()
            and f[:1].islower()
            and o != f
            and o not in ("null_action",)
            and f not in ("null_action",)
        ):
            rec["confirmed_inconsistency"] = True
        rec["semantic_divergence"] = semantic_divergence(o, f)

        mm_registered = component == "smf" or send_type not in (
            "registrationRequest",
            "deregistrationRequest",
        )
        for core, ret in (("open5gs", o), ("free5gc", f)):
            if ret[:1].islower() and ret not in ("null_action",):
                rec[f"{core}_wire_phi"] = bool(
                    query_component_violation(
                        component,
                        amf_oracle,
                        smf_oracle,
                        send_type,
                        ret,
                        wire_sht,
                        wire_sec,
                        new_msg=new_msg,
                        wire_mode=True,
                        mm_registered=mm_registered,
                        sm_state=None,
                    )
                )
            else:
                rec[f"{core}_wire_phi"] = False

        rec["confirmed_pv"] = rec["replay_ok"] and (
            rec["semantic_divergence"]
            or (
                rec["confirmed_inconsistency"]
                and (rec.get("open5gs_wire_phi") or rec.get("free5gc_wire_phi"))
            )
        )
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False, indent=2))

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    amf_n = sum(1 for r in results if r["component"] == "amf")
    smf_n = sum(1 for r in results if r["component"] == "smf")
    print(f"wrote {OUT} (amf={amf_n}, smf={smf_n})")
    print(
        "confirmed_inconsistency",
        sum(1 for r in results if r["confirmed_inconsistency"]),
        "semantic_divergence",
        sum(1 for r in results if r.get("semantic_divergence")),
        "confirmed_pv",
        sum(1 for r in results if r["confirmed_pv"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
