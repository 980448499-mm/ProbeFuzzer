"""Lab probes against Open5GS N11/SBI, PFCP, and NGAP (malicious gNB)."""
from __future__ import annotations

import json
import os
import random
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "seeds" / "iface"

SMF_SBI = os.getenv("SMF_SBI", "http://127.0.0.4:7777")
AMF_SBI = os.getenv("AMF_SBI", "http://127.0.0.5:7777")
NRF_SBI = os.getenv("NRF_SBI", "http://127.0.0.10:7777")
AMF_NGAP = (os.getenv("AMF_NGAP_HOST", "127.0.0.5"), int(os.getenv("AMF_NGAP_PORT", "38412")))
UPF_PFCP = (os.getenv("UPF_PFCP_HOST", "127.0.0.7"), int(os.getenv("UPF_PFCP_PORT", "8805")))
SMF_PFCP = (os.getenv("SMF_PFCP_HOST", "127.0.0.4"), int(os.getenv("SMF_PFCP_PORT", "8805")))

NFS = ("open5gs-amfd", "open5gs-smfd", "open5gs-upfd")
NGAP_PPID = 60
IPPROTO_SCTP = getattr(socket, "IPPROTO_SCTP", 132)
SOL_SCTP = IPPROTO_SCTP
SCTP_SNDINFO = 34

PLAIN_REG = bytes.fromhex(
    "7E004179000D0199F9070000000000000000741001002E04F0F0F0F02F020101700000530100"
)


def live_pids() -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {n: [] for n in NFS}
    try:
        ps = subprocess.check_output(["ps", "-eo", "pid,state,comm"], text=True, errors="replace")
    except Exception:
        return out
    for line in ps.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        pid, state, comm = parts[0], parts[1], parts[2]
        if state.startswith("Z"):
            continue
        if comm in out:
            out[comm].append(int(pid))
    return out


def log_alerts(log_path: Path, n_bytes: int = 20000) -> List[str]:
    if not log_path.exists():
        return []
    data = log_path.read_bytes()[-n_bytes:].decode("utf-8", "replace").lower()
    keys = ("fatal", "assertion", "ogs_assert", "aborted", "segfault", "core dumped", "should not be reached")
    hits = [k for k in keys if k in data]
    return hits


def crashed(before: Dict[str, List[int]], after: Dict[str, List[int]]) -> List[str]:
    dead = []
    for name in NFS:
        if before.get(name) and not after.get(name):
            dead.append(name)
    return dead


def mutate_bytes(seed: bytes, rng: random.Random) -> Tuple[str, bytes]:
    if not seed:
        return "empty", b"\x00"
    kind = rng.choice(
        [
            "bitflip",
            "byteflip",
            "truncate",
            "insert",
            "len_ffff",
            "repeat",
            "nas_stuff",
        ]
    )
    b = bytearray(seed)
    if kind == "bitflip" and b:
        i = rng.randrange(len(b))
        b[i] ^= 1 << rng.randrange(8)
    elif kind == "byteflip" and b:
        i = rng.randrange(len(b))
        b[i] = rng.randrange(256)
    elif kind == "truncate" and len(b) > 4:
        b = b[: rng.randint(1, len(b) - 1)]
    elif kind == "insert":
        i = rng.randrange(len(b) + 1)
        b[i:i] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 32)))
    elif kind == "len_ffff" and len(b) >= 4:
        b[2:4] = b"\xff\xff"
    elif kind == "repeat":
        b.extend(b[: min(64, len(b))] * rng.randint(2, 8))
    elif kind == "nas_stuff":
        nas = PLAIN_REG + bytes(rng.randrange(256) for _ in range(rng.randint(0, 40)))
        idx = bytes(b).find(b"\x7e\x00")
        if idx >= 0:
            b = b[:idx] + nas
        else:
            b.extend(nas)
    return kind, bytes(b)


def _curl(
    url: str,
    method: str,
    data: bytes,
    content_type: str,
    timeout: float = 3.0,
    extra_headers: Optional[List[str]] = None,
) -> Tuple[int, str, str, str]:
    hdr_path = Path("/tmp/iface_sbi_hdr")
    body_path = Path("/tmp/iface_sbi_body")
    for p in (hdr_path, body_path):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    cmd = [
        "curl",
        "-sS",
        "-m",
        str(timeout),
        "--http2-prior-knowledge",
        "-X",
        method,
        "-H",
        f"Content-Type: {content_type}",
        "-H",
        "Accept: application/json,application/problem+json",
        "-H",
        "User-Agent: AMF",
        "-D",
        str(hdr_path),
        "-o",
        str(body_path),
        "-w",
        "%{http_code}",
    ]
    for h in extra_headers or []:
        cmd.extend(["-H", h])
    cmd.extend(["--data-binary", "@-", url])
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout + 1)
    except subprocess.TimeoutExpired:
        return -1, "", "timeout", ""
    hdr = ""
    try:
        hdr = hdr_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    body = ""
    try:
        body = body_path.read_text(encoding="utf-8", errors="replace")[:1200]
    except Exception:
        pass
    status = 0
    try:
        status = int((p.stdout or b"0").decode().strip() or "0")
    except ValueError:
        status = 0
    if status == 0:
        for line in hdr.splitlines():
            if line.startswith("HTTP/"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status = int(parts[1])
    if status == 0 and body.lstrip().startswith("{"):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and isinstance(parsed.get("status"), int):
                status = parsed["status"]
        except json.JSONDecodeError:
            pass
    location = ""
    for line in hdr.splitlines():
        if line.lower().startswith("location:"):
            location = line.split(":", 1)[1].strip()
    err = p.stderr.decode("utf-8", "replace")[:200]
    return status, body, err, location


def _amf_nf_instance_id() -> str:
    """从 NRF 查询 AMF 的真实 NF instance ID（servingNfId 必须匹配，否则
    SMF 发 namf-comm 时按假 ID discovery 失败、session 被释放）。"""
    import json as _json
    try:
        out = subprocess.run(
            ["curl", "-s", "--http2-prior-knowledge", "--max-time", "3",
             "http://127.0.0.10:7777/nnrf-nfm/v1/nf-instances?nf-type=AMF"],
            capture_output=True, text=True, timeout=5)
        d = _json.loads(out.stdout)
        for item in d.get("_links", {}).get("item", []):
            href = item.get("href", "")
            if href:
                return href.rstrip("/").split("/")[-1]
    except Exception:
        pass
    return "11111111-2222-3333-4444-555555555555"


def _sm_context_json(**overrides) -> dict:
    base = {
        "supi": "imsi-999700000000001",
        "pei": "imeisv-4370816125816151",
        "pduSessionId": 5,
        "dnn": "internet",
        "sNssai": {"sst": 1},
        "servingNfId": _amf_nf_instance_id(),
        "anType": "3GPP_ACCESS",
        "ratType": "NR",
        "servingNetwork": {"mcc": "999", "mnc": "70"},
        "guami": {
            "plmnId": {"mcc": "999", "mnc": "70"},
            "amfId": "020040",
        },
        "ueLocation": {
            "nrLocation": {
                "tai": {"plmnId": {"mcc": "999", "mnc": "70"}, "tac": "000001"},
                "ncgi": {"plmnId": {"mcc": "999", "mnc": "70"}, "nrCellId": "000000010"},
            }
        },
        "n1SmMsg": {"contentId": "n1sm"},
        "smContextStatusUri": "http://127.0.0.5:7777/namf-callback/v1/imsi-999700000000001/sm-context-status",
    }
    base.update(overrides)
    return base


def _multipart(
    json_obj: dict,
    nas: Optional[bytes] = None,
    extra: Optional[List[Tuple[str, str, bytes]]] = None,
) -> Tuple[bytes, str]:
    """Match Open5GS build_multipart(): JSON first (no Content-Id), then binary parts."""
    boundary = "ifaceprobe"
    js = json.dumps(json_obj, separators=(",", ":")).encode()
    body = f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode() + js
    parts: List[Tuple[str, str, bytes]] = []
    if nas is not None:
        parts.append(("n1sm", "application/vnd.3gpp.5gnas", nas))
    parts.extend(extra or [])
    for cid, pctype, blob in parts:
        body += (
            f"\r\n--{boundary}\r\nContent-Id: {cid}\r\nContent-Type: {pctype}\r\n\r\n".encode()
            + blob
        )
    body += f"\r\n--{boundary}--\r\n".encode()
    ctype = f"multipart/related; boundary={boundary}"
    return body, ctype


class _Bits:
    def __init__(self) -> None:
        self._b: List[int] = []

    def put(self, val: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            self._b.append((val >> i) & 1)

    def align(self) -> None:
        while len(self._b) % 8:
            self._b.append(0)

    def raw(self) -> bytes:
        self.align()
        out = bytearray()
        for i in range(0, len(self._b), 8):
            v = 0
            for j in range(8):
                v = (v << 1) | self._b[i + j]
            out.append(v)
        return bytes(out)


def n2_setup_rsp_transfer(ipv4: str = "127.0.0.1", teid: int = 1, qfi: int = 1) -> bytes:
    """APER PDUSessionResourceSetupResponseTransfer (IPv4 GTP-U + one QFI)."""
    ip = socket.inet_aton(ipv4)
    b = _Bits()
    b.put(0, 1)
    b.put(0, 4)
    b.put(0, 1)
    b.put(0, 1)
    b.put(0, 1)
    b.put(0, 1)
    b.put(0, 1)
    b.put(0, 1)
    b.put(31, 8)
    b.align()
    for x in ip:
        b.put(x, 8)
    b.align()
    for x in teid.to_bytes(4, "big"):
        b.put(x, 8)
    b.put(0, 6)
    b.put(0, 1)
    b.put(0, 2)
    b.put(0, 1)
    b.put(qfi & 0x3F, 6)
    return b.raw()


def ngap_find_ie(pdu: bytes, ie_id: int) -> Optional[Tuple[int, int, bytes]]:
    """Return (value_offset, value_len, value) for a 2+2+value IE after the IE count."""
    if len(pdu) < 8:
        return None
    n_ie = pdu[6]
    off = 7
    for _ in range(n_ie):
        if off + 4 > len(pdu):
            return None
        iid = (pdu[off] << 8) | pdu[off + 1]
        ln = (pdu[off + 2] << 8) | pdu[off + 3]
        off += 4
        if off + ln > len(pdu):
            return None
        if iid == ie_id:
            return off, ln, pdu[off : off + ln]
        off += ln
    return None


def ngap_set_ie_u16(pdu: bytes, ie_id: int, value: int) -> bytes:
    found = ngap_find_ie(pdu, ie_id)
    if not found:
        return pdu
    off, ln, _ = found
    if ln < 2:
        return pdu
    b = bytearray(pdu)
    b[off + ln - 2] = (value >> 8) & 0xFF
    b[off + ln - 1] = value & 0xFF
    return bytes(b)


def ngap_amf_ue_id(pdu: bytes) -> int:
    found = ngap_find_ie(pdu, 0x000A)
    if not found:
        return 1
    _, _, val = found
    n = 0
    for x in val:
        n = (n << 8) | x
    return n or 1


def mutate_after(seed: bytes, offset: int, rng: random.Random) -> Tuple[str, bytes]:
    """Flip one bit after `offset` so headers/NGAP wrapping stay intact."""
    if not seed:
        return "empty", b"\x00"
    if len(seed) <= offset:
        return mutate_bytes(seed, rng)
    b = bytearray(seed)
    i = rng.randrange(offset, len(b))
    b[i] ^= 1 << rng.randrange(8)
    return "inplace", bytes(b)


def gsm_nas() -> bytes:
    p = SEED_DIR / "nas" / "pdu_sess_est.bin"
    if p.exists():
        return p.read_bytes()
    return bytes.fromhex("2e0501c1ffff91a1")


def classify_ngap(pdu: bytes) -> str:
    if not pdu:
        return "empty"
    proc = pdu[1] if len(pdu) > 1 else 0
    kind = {0x00: "init", 0x20: "ok", 0x40: "fail"}.get(pdu[0] & 0xE0, f"b{pdu[0]:02x}")
    names = {
        4: "DownlinkNAS",
        9: "ErrorInd",
        14: "NGReset",
        15: "InitialUE",
        21: "NGSetup",
        41: "UECtxRel",
        46: "UplinkNAS",
    }
    return f"{kind}:{names.get(proc, f'proc{proc}')}:{len(pdu)}"


def sbi_create_sm_context(nas: Optional[bytes] = None) -> dict:
    nas = nas or gsm_nas()
    body, ctype = _multipart(_sm_context_json(), nas)
    status, resp, err, location = _curl(
        f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts",
        "POST",
        body,
        ctype,
        timeout=5.0,
    )
    return {"status": status, "body": resp, "err": err, "location": location}


def sbi_modify(url: str, payload: bytes, ctype: str = "application/json", timeout: float = 5.0) -> dict:
    status, resp, err, location = _curl(url, "POST", payload, ctype, timeout=timeout)
    return {"status": status, "body": resp, "err": err, "location": location}


def sbi_modify_n2(url: str, n2: bytes, info_type: str = "PDU_RES_SETUP_RSP") -> dict:
    body, ctype = _multipart(
        {"n2SmInfo": {"contentId": "n2"}, "n2SmInfoType": info_type},
        extra=[("n2", "application/vnd.3gpp.ngap", n2)],
    )
    return sbi_modify(url, body, ctype, timeout=8.0)


def modify_payloads(rng: random.Random) -> List[Tuple[str, bytes]]:
    """Fuzz payloads used AFTER N2 activate and BEFORE release."""
    return [
        ("upcnx_activating", b'{"upCnxState":"ACTIVATING"}'),
        ("upcnx_deactivated", b'{"upCnxState":"DEACTIVATED"}'),
        ("upcnx_suspended", b'{"upCnxState":"SUSPENDED"}'),
        ("ue_req_mod", b'{"requestIndication":"UE_REQ_PDU_SES_MOD","upCnxState":"DEACTIVATED"}'),
        ("n2_absent", b'{"n2SmInfo":{"contentId":"n2"},"n2SmInfoType":"PDU_RES_SETUP_RSP"}'),
        ("type_conf", json.dumps({"upCnxState": 4, "requestIndication": ["x"]}).encode()),
        ("empty_obj", b"{}"),
        ("huge_dnn", json.dumps({"dnn": "x" * 8000}).encode()),
        (
            "inplace_json",
            mutate_after(
                b'{"ueLocation":{"nrLocation":{"tai":{"plmnId":{"mcc":"999","mnc":"70"},"tac":"000001"}}}}',
                2,
                rng,
            )[1],
        ),
    ]


def _pfcp_type(pdu: bytes) -> int:
    return pdu[1] if len(pdu) > 1 else -1


def _pfcp_replace_ipv4(payload: bytes, old: bytes, new: bytes) -> bytes:
    if len(old) != 4 or len(new) != 4:
        return payload
    return payload.replace(old, new)


def _pfcp_heartbeat_resp(req: bytes) -> bytes:
    if len(req) < 4:
        return b""
    b = bytearray(req)
    b[1] = 2
    return bytes(b)


def _pfcp_set_header_seid(pdu: bytes, seid: int) -> bytes:
    b = bytearray(pdu)
    if not b or not (b[0] & 0x01) or len(b) < 12:
        return pdu
    b[4:12] = seid.to_bytes(8, "big")
    return bytes(b)


def _pfcp_set_fseid(pdu: bytes, seid: int, ipv4: bytes) -> bytes:
    """Patch first F-SEID (IE 57 / 0x39) and the header SEID."""
    b = bytearray(_pfcp_set_header_seid(pdu, seid))
    off = 16 if (b[0] & 0x01) else 8
    while off + 4 <= len(b):
        itype = (b[off] << 8) | b[off + 1]
        ln = (b[off + 2] << 8) | b[off + 3]
        val_off = off + 4
        if val_off + ln > len(b):
            break
        if itype == 0x0039 and ln >= 13 and b[val_off] & 0x02:
            b[val_off + 1 : val_off + 9] = seid.to_bytes(8, "big")
            b[val_off + 9 : val_off + 13] = ipv4
            break
        off = val_off + ln
    return bytes(b)


def _pfcp_drain(sock: socket.socket, deadline: float) -> List[bytes]:
    got = []
    while time.time() < deadline:
        try:
            data, _ = sock.recvfrom(4096)
        except socket.timeout:
            break
        kind = _pfcp_type(data)
        if kind == 1:
            resp = _pfcp_heartbeat_resp(data)
            if resp:
                sock.sendto(resp, sock.getpeername() if False else UPF_PFCP)
            continue
        got.append(data)
        if kind in (6, 51, 53, 55):
            break
    return got


def pfcp_assoc_then_session(session_payload: bytes, target: Tuple[str, int]) -> Tuple[bytes, bytes]:
    """Backward-compatible: assoc then one Session Establishment."""
    a_rx, s_rx, sock = _pfcp_assoc_est(session_payload, target, seid=None)
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    return a_rx, s_rx


def _pfcp_assoc_est(
    session_payload: bytes,
    target: Tuple[str, int],
    seid: Optional[int] = None,
) -> Tuple[bytes, bytes, Optional[socket.socket]]:
    assoc = load_seed("pfcp/assoc_smf_to_upf.bin") or load_seed("pfcp/type_5_56.bin")
    smf_ip = bytes.fromhex("7f000004")
    probe_ip = bytes.fromhex("7f000001")
    assoc = _pfcp_replace_ipv4(assoc, smf_ip, probe_ip)
    session_payload = _pfcp_replace_ipv4(session_payload, smf_ip, probe_ip)
    if seid is None:
        seid = 0xC0FFEE00 + (int(time.time() * 1000) & 0xFF)
    session_payload = _pfcp_set_fseid(session_payload, seid, probe_ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.35)
    sock.bind(("127.0.0.1", 0))
    a_rx = b""
    s_rx = b""
    try:
        sock.sendto(assoc, target)
        deadline = time.time() + 1.4
        sent_session = False
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                if not sent_session and a_rx:
                    sock.sendto(session_payload, target)
                    sent_session = True
                continue
            kind = _pfcp_type(data)
            if kind == 6 and not a_rx:
                a_rx = data
                if not sent_session:
                    sock.sendto(session_payload, target)
                    sent_session = True
            elif kind == 1:
                resp = _pfcp_heartbeat_resp(data)
                if resp:
                    sock.sendto(resp, target)
            elif kind == 51:
                s_rx = data
                break
            elif kind not in (6, 1) and sent_session and not s_rx:
                s_rx = data
        if not sent_session:
            sock.sendto(session_payload, target)
            try:
                data, _ = sock.recvfrom(4096)
                if _pfcp_type(data) == 51 or not s_rx:
                    s_rx = data
            except socket.timeout:
                pass
        return a_rx, s_rx, sock
    except Exception:
        sock.close()
        raise


def pfcp_sweep_delete(target: Tuple[str, int], seids: List[int]) -> int:
    """Associate as 127.0.0.1 and delete leftover sessions so the UE IP pool can recover."""
    assoc = load_seed("pfcp/assoc_smf_to_upf.bin") or load_seed("pfcp/type_5_56.bin")
    assoc = _pfcp_replace_ipv4(assoc, bytes.fromhex("7f000004"), bytes.fromhex("7f000001"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.15)
    sock.bind(("127.0.0.1", 0))
    n = 0
    try:
        sock.sendto(assoc, target)
        try:
            data, _ = sock.recvfrom(4096)
            if _pfcp_type(data) == 1:
                sock.sendto(_pfcp_heartbeat_resp(data), target)
        except socket.timeout:
            pass
        for seid in seids:
            rx = pfcp_delete(sock, seid, target)
            if rx:
                n += 1
    finally:
        sock.close()
    return n


def pfcp_delete(sock: socket.socket, seid: int, target: Tuple[str, int]) -> bytes:
    pdu = load_seed("pfcp/type_54_16.bin")
    if not pdu:
        return b""
    pdu = _pfcp_set_header_seid(pdu, seid)
    try:
        sock.sendto(pdu, target)
        try:
            data, _ = sock.recvfrom(4096)
            if _pfcp_type(data) == 1:
                sock.sendto(_pfcp_heartbeat_resp(data), target)
                data, _ = sock.recvfrom(4096)
            return data
        except socket.timeout:
            return b""
    except OSError:
        return b""


def pfcp_est_then_modify(
    est: bytes,
    mod: bytes,
    target: Tuple[str, int],
    seid: int,
) -> Tuple[bytes, bytes, bytes]:
    """Assoc + Session Est + Session Modification + Session Deletion on one UDP flow."""
    a_rx, s_rx, sock = _pfcp_assoc_est(est, target, seid=seid)
    m_rx = b""
    try:
        if sock is None:
            return a_rx, s_rx, m_rx
        probe_ip = bytes.fromhex("7f000001")
        mod = _pfcp_replace_ipv4(mod, bytes.fromhex("7f000004"), probe_ip)
        mod = _pfcp_set_header_seid(mod, seid)
        if s_rx and _pfcp_type(s_rx) == 51:
            sock.sendto(mod, target)
            deadline = time.time() + 1.0
            while time.time() < deadline:
                try:
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    break
                kind = _pfcp_type(data)
                if kind == 1:
                    sock.sendto(_pfcp_heartbeat_resp(data), target)
                    continue
                if kind == 53 or not m_rx:
                    m_rx = data
                if kind == 53:
                    break
        pfcp_delete(sock, seid, target)
    finally:
        if sock is not None:
            sock.close()
    return a_rx, s_rx, m_rx


def sbi_cases(rng: random.Random) -> List[dict]:
    nas = gsm_nas()
    cases = [
        {
            "name": "smf_smctx_json_only",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts",
            "method": "POST",
            "ctype": "application/json",
            "data": json.dumps(_sm_context_json()).encode(),
        },
        {
            "name": "smf_smctx_multipart",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts",
            "method": "POST",
            "data_ctype": _multipart(_sm_context_json(), nas),
        },
        {
            "name": "smf_smctx_missing_snssai",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts",
            "method": "POST",
            "data_ctype": _multipart(_sm_context_json(sNssai=None), nas),
        },
        {
            "name": "smf_smctx_type_confusion",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts",
            "method": "POST",
            "ctype": "application/json",
            "data": json.dumps(
                {
                    "supi": ["imsi-999700000000001"],
                    "pduSessionId": "five",
                    "sNssai": "internet",
                    "servingNetwork": 99970,
                    "anType": 3,
                }
            ).encode(),
        },
        {
            "name": "smf_smctx_nested_bomb",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts",
            "method": "POST",
            "ctype": "application/json",
            "data": json.dumps({"a": {"b": {"c": {"d": list(range(200))}}}}).encode(),
        },
        {
            "name": "smf_modify_no_session",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/sm-contexts/deadbeef/modify",
            "method": "POST",
            "ctype": "application/json",
            "data": b'{"ueLocation":{"nrLocation":{}}}',
        },
        {
            "name": "smf_pdu_modify_invalid_state",
            "url": f"{SMF_SBI}/nsmf-pdusession/v1/pdu-sessions/1/modify",
            "method": "POST",
            "ctype": "application/json",
            "data": b'{"requestIndication":"UE_REQ_PDU_SES_MOD","upCnxState":"SUSPENDED"}',
        },
        {
            "name": "amf_uectx_create",
            "url": f"{AMF_SBI}/namf-comm/v1/ue-contexts/imsi-999700000000001",
            "method": "PUT",
            "ctype": "application/json",
            "data": json.dumps(
                {
                    "supi": "imsi-999700000000001",
                    "gpsi": "msisdn-9997000001",
                    "anType": "3GPP_ACCESS",
                }
            ).encode(),
        },
        {
            "name": "amf_n1n2_transfer",
            "url": f"{AMF_SBI}/namf-comm/v1/ue-contexts/imsi-999700000000001/n1-n2-messages",
            "method": "POST",
            "ctype": "application/json",
            "data": b'{"n1MessageContainer":{"n1MessageClass":"SM","n1MessageContent":{"contentId":"n1"}}}',
        },
        {
            "name": "nrf_nf_list",
            "url": f"{NRF_SBI}/nnrf-nfm/v1/nf-instances",
            "method": "GET",
            "ctype": "application/json",
            "data": b"",
        },
    ]
    extra = []
    for c in cases[:4]:
        blob = c.get("data")
        if blob is None and "data_ctype" in c:
            blob = c["data_ctype"][0]
        if not blob:
            continue
        kind, mut = mutate_bytes(blob, rng)
        extra.append(
            {
                "name": c["name"] + "_mut_" + kind,
                "url": c["url"],
                "method": c["method"],
                "ctype": c.get("ctype") or c.get("data_ctype", ("", "application/json"))[1],
                "data": mut,
            }
        )
    return cases + extra


def send_sbi(case: dict) -> dict:
    if "data_ctype" in case:
        data, ctype = case["data_ctype"]
    else:
        data, ctype = case.get("data", b""), case.get("ctype", "application/json")
    method = case.get("method", "POST")
    if method == "GET":
        cmd = [
            "curl",
            "-sS",
            "-m",
            "3",
            "--http2-prior-knowledge",
            "-D",
            "-",
            "-o",
            "/tmp/iface_sbi_body",
            case["url"],
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=4)
            hdr = p.stdout.decode("utf-8", "replace")
            status = 0
            for line in hdr.splitlines():
                if line.startswith("HTTP/"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        status = int(parts[1])
            body = Path("/tmp/iface_sbi_body").read_text("utf-8", "replace")[:400] if Path("/tmp/iface_sbi_body").exists() else ""
            return {"status": status, "body": body, "err": p.stderr.decode("utf-8", "replace")[:160]}
        except Exception as e:
            return {"status": -1, "body": "", "err": str(e)}
    status, body, err, location = _curl(case["url"], method, data, ctype)
    return {"status": status, "body": body, "err": err, "location": location}


def send_pfcp(payload: bytes, target: Tuple[str, int], timeout: float = 1.0) -> bytes:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, target)
        try:
            data, _ = sock.recvfrom(4096)
            return data
        except socket.timeout:
            return b""
    finally:
        sock.close()


def _sctp_send(payloads: List[bytes], host: str, port: int, wait: float = 0.35) -> bytes:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, IPPROTO_SCTP)
    s.settimeout(2.0)
    recvd = b""
    try:
        s.connect((host, port))
        sndinfo = struct.pack("HHIIi", 0, 0, socket.htonl(NGAP_PPID), 0, 0)
        for pdu in payloads:
            try:
                s.sendmsg([pdu], [(SOL_SCTP, SCTP_SNDINFO, sndinfo)])
            except OSError:
                s.sendall(pdu)
            time.sleep(0.05)
        time.sleep(wait)
        try:
            recvd = s.recv(8192)
        except socket.timeout:
            recvd = b""
    finally:
        try:
            s.close()
        except Exception:
            pass
    return recvd


def load_seed(rel: str) -> bytes:
    p = SEED_DIR / rel
    return p.read_bytes() if p.exists() else b""


def send_ngap(kind: str, payload: bytes) -> bytes:
    setup = load_seed("ngap/ngsetup.bin")
    if kind == "bare":
        return _sctp_send([payload], *AMF_NGAP)
    if kind == "setup_then":
        return _sctp_send([setup, payload], *AMF_NGAP)
    return _sctp_send([payload], *AMF_NGAP)


def ngap_setup_then(payload: bytes, wait: float = 0.4) -> Tuple[bytes, bytes]:
    """Unmodified NGSetup, then a (possibly mutated) follow-up on the same SCTP assoc."""
    rxs, rxs_rest = ngap_assoc_messages([payload], wait=wait)
    return rxs, (rxs_rest[0] if rxs_rest else b"")


def ngap_assoc_messages(payloads: List[bytes], wait: float = 0.45) -> Tuple[bytes, List[bytes]]:
    """NGSetup then a sequence of NGAP PDUs on one SCTP association."""
    setup = load_seed("ngap/ngsetup.bin")
    host, port = AMF_NGAP
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, IPPROTO_SCTP)
    s.settimeout(2.0)
    rx_setup, replies = b"", []
    sndinfo = struct.pack("HHIIi", 0, 0, socket.htonl(NGAP_PPID), 0, 0)

    def _send(pdu: bytes) -> None:
        try:
            s.sendmsg([pdu], [(SOL_SCTP, SCTP_SNDINFO, sndinfo)])
        except OSError:
            s.sendall(pdu)

    def _recv() -> bytes:
        try:
            return s.recv(8192)
        except socket.timeout:
            return b""

    try:
        s.connect((host, port))
        _send(setup)
        time.sleep(wait)
        rx_setup = _recv()
        for pdu in payloads:
            _send(pdu)
            time.sleep(wait)
            replies.append(_recv())
    finally:
        try:
            s.close()
        except Exception:
            pass
    return rx_setup, replies


def ngap_reg_then_ul(initial_ue: bytes, uplink: bytes, wait: float = 0.45) -> Tuple[bytes, bytes, bytes]:
    """NGSetup → InitialUE → DownlinkNAS → UplinkNAS on the same association."""
    setup = load_seed("ngap/ngsetup.bin")
    host, port = AMF_NGAP
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, IPPROTO_SCTP)
    s.settimeout(2.0)
    rx_setup, rx_ue, rx_ul = b"", b"", b""
    sndinfo = struct.pack("HHIIi", 0, 0, socket.htonl(NGAP_PPID), 0, 0)

    def _send(pdu: bytes) -> None:
        try:
            s.sendmsg([pdu], [(SOL_SCTP, SCTP_SNDINFO, sndinfo)])
        except OSError:
            s.sendall(pdu)

    def _recv() -> bytes:
        try:
            return s.recv(8192)
        except socket.timeout:
            return b""

    try:
        s.connect((host, port))
        _send(setup)
        time.sleep(wait)
        rx_setup = _recv()
        _send(initial_ue)
        time.sleep(wait)
        rx_ue = _recv()
        amf_id = ngap_amf_ue_id(rx_ue) if rx_ue else 1
        ul = ngap_set_ie_u16(uplink, 0x000A, amf_id)
        ul = ngap_set_ie_u16(ul, 0x0055, 1)
        _send(ul)
        time.sleep(wait)
        rx_ul = _recv()
    finally:
        try:
            s.close()
        except Exception:
            pass
    return rx_setup, rx_ue, rx_ul


def pfcp_targets() -> List[Tuple[str, Tuple[str, int]]]:
    return [("upf", UPF_PFCP), ("smf", SMF_PFCP)]
