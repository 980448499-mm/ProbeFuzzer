#!/usr/bin/env python3
"""Capture the first NGSetupRequest from a live UERANSIM gNB on lo."""
from __future__ import annotations

import socket
import struct
import subprocess
import time
from pathlib import Path

OUT = Path("/corefuzzer/seeds/iface/ngap/ngsetup.bin")


def ipv4_sctp(pkt: bytes):
    if len(pkt) >= 14 and pkt[12:14] == b"\x08\x00":
        ip = pkt[14:]
    else:
        ip = pkt
    if len(ip) < 20 or (ip[0] >> 4) != 4 or ip[9] != 132:
        return None
    ihl = (ip[0] & 0xF) * 4
    src = socket.inet_ntoa(ip[12:16])
    dst = socket.inet_ntoa(ip[16:20])
    return src, dst, ip[ihl:]


def sctp_data(l4: bytes):
    out = []
    if len(l4) < 12:
        return out
    sport, dport = struct.unpack_from(">HH", l4, 0)
    off = 12
    while off + 4 <= len(l4):
        ctype, flags, clen = struct.unpack_from(">BBH", l4, off)
        if clen < 4 or off + clen > len(l4):
            break
        if ctype == 0 and clen >= 16:
            ppid = struct.unpack_from(">I", l4, off + 12)[0]
            out.append((sport, dport, ppid, l4[off + 16 : off + clen]))
        off = (off + clen + 3) & ~3
    return out


def main() -> None:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    s.bind(("lo", 0))
    s.settimeout(0.4)

    subprocess.call(["pkill", "-9", "-x", "nr-gnb"])
    time.sleep(0.5)
    subprocess.Popen(
        ["nr-gnb", "-c", "/corefuzzer_deps/ueransim/config/open5gs-gnb.yaml"],
        stdout=open("/corefuzzer/logs/gnb.log", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    found = []
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            pkt = s.recv(65535)
        except socket.timeout:
            continue
        parsed = ipv4_sctp(pkt)
        if not parsed:
            continue
        _src, _dst, l4 = parsed
        for sport, dport, ppid, payload in sctp_data(l4):
            if dport == 38412 and payload[:2] == b"\x00\x15":
                found.append(payload)
                print(f"GOT sport={sport} ppid={ppid} len={len(payload)} {payload.hex()}")
                break
        if found:
            break
    s.close()
    if not found:
        print("NO_NGSETUP")
        return
    payload = found[0]
    OUT.write_bytes(payload)
    print(f"SAVED {len(payload)} bytes -> {OUT}")


if __name__ == "__main__":
    main()
