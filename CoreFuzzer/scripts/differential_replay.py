#!/usr/bin/env python3
"""Differential replay of wire-Φ hits on Open5GS (required) and free5GC (optional)."""
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from objects.oracle import Oracle  # noqa: E402
from objects.wire_nas import normalize_wire_security  # noqa: E402

UE_HOST = "127.0.0.1"
UE_PORT = int(os.environ.get("UE_PORT", "45678"))


def recv_line(sock: socket.socket, timeout: float = 8.0) -> str:
    sock.settimeout(timeout)
    data = sock.recv(8192)
    return data.decode(errors="replace").strip() if data else ""


def connect_ue() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((UE_HOST, UE_PORT))
    try:
        recv_line(s, 3)
    except Exception:
        pass
    return s


def send_cmd(sock: socket.socket, cmd: str, timeout: float = 10.0) -> str:
    sock.send(cmd.encode())
    return recv_line(sock, timeout)


def replay_pdu(sock: socket.socket, hex_pdu: str, secmod: int, sht: int) -> str:
    ok = send_cmd(sock, "testMessage", 5)
    if "OK" not in ok.upper():
        return f"HANDSHAKE_FAIL:{ok}"
    sock.send(f"{hex_pdu}:{secmod}:{sht}".encode())
    return recv_line(sock, 10) or "TIMEOUT"


def probe_free5gc() -> bool:
    """Best-effort: free5GC AMF typically exposes SCTP 38412 on a container IP."""
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}} {{.Image}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return any("free5gc" in line.lower() and "amf" in line.lower() for line in out.stdout.splitlines())
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hits", default=str(ROOT / "wire_phi_hits.csv"))
    ap.add_argument("--out", default=str(ROOT / "differential_replay_results.json"))
    args = ap.parse_args()

    hits_path = Path(args.hits)
    if not hits_path.exists():
        print(f"No hits file: {hits_path}")
        Path(args.out).write_text("[]", encoding="utf-8")
        return 0

    rows = list(csv.DictReader(hits_path.open(encoding="utf-8-sig")))
    free5gc_up = probe_free5gc()
    print(f"hits={len(rows)} free5gc_amf_detected={free5gc_up}")

    results = []
    for i, row in enumerate(rows, 1):
        send_type = row.get("send_type") or row.get("send_type_inferred")
        new_msg = row["new_msg"]
        sht = int(row.get("sht") or 0)
        secmod = int(row.get("secmod") or 1)
        wire_sht, wire_sec, meta = normalize_wire_security(new_msg, sht, secmod)
        print(f"\n[{i}/{len(rows)}] {send_type} wire_sht={wire_sht} secmod={wire_sec}")

        open5gs_ret = "SKIP"
        try:
            sock = connect_ue()
            # best-effort prefix for auth-related
            if send_type in ("authenticationResponse", "authenticationFailure", "identityResponse"):
                send_cmd(sock, "registrationRequest", 12)
                time.sleep(0.3)
            open5gs_ret = replay_pdu(sock, new_msg, wire_sec, wire_sht)
            sock.close()
        except Exception as e:
            open5gs_ret = f"ERR:{e}"

        free5gc_ret = "NOT_AVAILABLE"
        if free5gc_up:
            free5gc_ret = "DETECTED_BUT_REPLAY_NOT_WIRED"
            # Full free5GC+UERANSIM dual-stack wiring is environment-specific;
            # keep explicit placeholder so results stay honest.

        oracle = Oracle()
        phi = bool(
            oracle.query_message(
                send_type,
                open5gs_ret if open5gs_ret[:1].islower() else "",
                wire_sht,
                wire_sec,
                new_msg=new_msg,
                wire_mode=True,
            )
        ) if open5gs_ret[:1].islower() else False

        confirmed = False
        reason = []
        if open5gs_ret.startswith(("ERR", "HANDSHAKE", "TIMEOUT", "NOT")):
            reason.append("open5gs_replay_failed")
        elif open5gs_ret in ("registrationReject", "authenticationReject", "serviceReject", "null_action"):
            reason.append("open5gs_normal_or_no_send")
        elif phi and free5gc_up and free5gc_ret not in (open5gs_ret, "NOT_AVAILABLE", "DETECTED_BUT_REPLAY_NOT_WIRED"):
            confirmed = True
            reason.append("differential_mismatch")
        elif phi:
            reason.append("wire_phi_hit_needs_clause_check")
        else:
            reason.append("not_confirmed")

        rec = {
            **row,
            "wire_sht": wire_sht,
            "wire_secmod": wire_sec,
            "open5gs_ret": open5gs_ret,
            "free5gc_ret": free5gc_ret,
            "wire_phi_on_replay": phi,
            "confirmed_pv": confirmed,
            "reason": ";".join(reason),
            "meta": meta,
        }
        results.append(rec)
        print(f"  open5gs={open5gs_ret} confirmed={confirmed} ({rec['reason']})")

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    conf = sum(1 for r in results if r["confirmed_pv"])
    print(f"\nconfirmed_pv={conf}/{len(results)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
