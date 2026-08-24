"""Wire-faithful NAS helpers and CN-oriented Φ oracle."""
from __future__ import annotations

from typing import List, Optional, Tuple

# 3GPP 24.501 message types (matches UERANSIM / Open5GS naming)
_GMM_MSG_TYPE = {
    0x41: "registrationRequest",
    0x42: "registrationAccept",
    0x43: "registrationComplete",
    0x44: "registrationReject",
    0x45: "deregistrationRequest",
    0x46: "deregistrationAccept",
    0x47: "deregistrationRequest",
    0x48: "deregistrationAccept",
    0x4C: "serviceRequest",
    0x4D: "serviceReject",
    0x4E: "serviceAccept",
    0x54: "configurationUpdateCommand",
    0x55: "configurationUpdateComplete",
    0x56: "authenticationRequest",
    0x57: "authenticationResponse",
    0x58: "authenticationReject",
    0x59: "authenticationFailure",
    0x5A: "authenticationResult",
    0x5B: "identityRequest",
    0x5C: "identityResponse",
    0x5D: "securityModeCommand",
    0x5E: "securityModeComplete",
    0x5F: "securityModeReject",
    0x64: "gmmStatus",
    0x67: "ulNasTransport",
    0x68: "dlNasTransport",
}

_GSM_MSG_TYPE = {
    0xC1: "pduSessionEstablishmentRequest",
    0xC2: "pduSessionEstablishmentAccept",
    0xC3: "pduSessionEstablishmentReject",
    0xC5: "pduSessionAuthenticationCommand",
    0xC6: "pduSessionAuthenticationComplete",
    0xC7: "pduSessionAuthenticationResult",
    0xC9: "pduSessionModificationRequest",
    0xCA: "pduSessionModificationReject",
    0xCB: "pduSessionModificationCommand",
    0xCC: "pduSessionModificationComplete",
    0xCD: "pduSessionModificationCommandReject",
    0xD1: "pduSessionReleaseRequest",
    0xD2: "pduSessionReleaseReject",
    0xD3: "pduSessionReleaseCommand",
    0xD4: "pduSessionReleaseComplete",
    0xD6: "gsmStatus",
}

# Prefer CN→UE downlink types when inferring ret_type from hex
_CN_DOWNLINK_PREFERENCE = (
    "authenticationRequest",
    "identityRequest",
    "securityModeCommand",
    "registrationAccept",
    "registrationReject",
    "authenticationReject",
    "authenticationResult",
    "configurationUpdateCommand",
    "deregistrationRequest",
    "deregistrationAccept",
    "serviceReject",
    "serviceAccept",
    "dlNasTransport",
    "pduSessionEstablishmentAccept",
    "pduSessionEstablishmentReject",
    "pduSessionModificationCommand",
    "pduSessionModificationReject",
    "pduSessionReleaseCommand",
    "gmmStatus",
    "gsmStatus",
)


NORMAL_REJECTS = {
    "registrationReject",
    "authenticationReject",
    "serviceReject",
    "securityModeReject",
}

SM_NORMAL_REJECTS = {
    "gmmStatus",
    "null_action",
}

# Network continued / advanced the procedure (not a pure reject)
CONTINUATION = {
    "authenticationRequest",
    "authenticationResult",
    "securityModeCommand",
    "registrationAccept",
    "configurationUpdateCommand",
    "identityRequest",
    "deregistrationAccept",
    "deregistrationRequest",
    "serviceAccept",
    "pduSessionEstablishmentAccept",
    "dlNasTransport",
}

SM_CONTINUATION = {
    "pduSessionEstablishmentAccept",
    "pduSessionModificationCommand",
    "pduSessionModificationReject",
    "pduSessionReleaseCommand",
    "dlNasTransport",
}


def _hex_to_bytes(hex_str: Optional[str]) -> bytes:
    if not hex_str:
        return b""
    h = hex_str.strip().upper()
    if len(h) % 2:
        h = h[:-1]
    try:
        return bytes.fromhex(h)
    except ValueError:
        return b""


def parse_nas_message_type_at(raw: bytes, offset: int) -> Tuple[Optional[str], int]:
    """Parse one NAS PDU at offset; return (symbol_name, next_scan_offset)."""
    n = len(raw)
    if offset + 3 > n:
        return None, n

    epd = raw[offset]
    if epd == 0x7E:
        sht = raw[offset + 1] & 0x0F
        if sht == 0:
            name = _GMM_MSG_TYPE.get(raw[offset + 2])
            return name, offset + 3
        # Secured 5GMM: 7E | SHT | MAC(4) | SN(1) | payload
        if offset + 7 < n and raw[offset + 7] == 0x7E:
            inner_name, _ = parse_nas_message_type_at(raw, offset + 7)
            return inner_name, offset + 7
        return None, offset + 1

    if epd == 0x2E:
        if offset + 4 > n:
            return None, n
        name = _GSM_MSG_TYPE.get(raw[offset + 3])
        return name, offset + 4

    return None, offset + 1


def parse_nas_message_types_from_hex(hex_str: Optional[str]) -> List[str]:
    """Scan a hex buffer and collect all decodable NAS message type names."""
    raw = _hex_to_bytes(hex_str)
    if not raw:
        return []

    found: List[str] = []
    i = 0
    while i < len(raw):
        if raw[i] not in (0x7E, 0x2E):
            i += 1
            continue
        name, nxt = parse_nas_message_type_at(raw, i)
        if name:
            found.append(name)
        i = max(i + 1, nxt)
    return found


def resolve_ret_type(ret_type: Optional[str], ret_msg: Optional[str] = None) -> str:
    """Use UE ret_type when present; otherwise infer from downlink ret_msg hex."""
    if ret_type and str(ret_type).strip():
        return str(ret_type).strip()
    names = parse_nas_message_types_from_hex(ret_msg)
    if not names:
        return ""
    for preferred in _CN_DOWNLINK_PREFERENCE:
        if preferred in names:
            return preferred
    return names[-1]


def wire_sht_from_hex(new_msg: Optional[str]) -> Optional[int]:
    if not new_msg:
        return None
    h = new_msg.strip().upper()
    if len(h) < 4 or not h.startswith("7E"):
        return None
    try:
        return int(h[2:4], 16) & 0x0F
    except ValueError:
        return None


def normalize_wire_security(
    new_msg: Optional[str],
    sht: Optional[int],
    secmod: Optional[int],
) -> Tuple[int, int, dict]:
    """Prefer SHT from on-wire PDU; keep reported secmod when present."""
    meta = {"wire_sht": None, "reported_sht": sht, "reported_secmod": secmod, "used_wire_sht": False}
    ws = wire_sht_from_hex(new_msg)
    meta["wire_sht"] = ws
    out_sht = int(sht) if sht is not None else 0
    out_sec = int(secmod) if secmod is not None else 0
    if ws is not None:
        out_sht = ws
        meta["used_wire_sht"] = True
        # Plaintext on wire => effective no-security send mode
        if ws == 0 and out_sec != 1:
            out_sec = 1
            meta["forced_secmod_for_plaintext"] = True
    return out_sht, out_sec, meta


def is_cn_interesting_response(ret_type: str) -> bool:
    if not ret_type or ret_type in ("", "gmmStatus", "null_action"):
        return False
    if ret_type in NORMAL_REJECTS:
        return False
    return ret_type in CONTINUATION or ret_type.endswith("Accept") or ret_type.endswith("Command")


def is_sm_cn_interesting_response(ret_type: str) -> bool:
    if not ret_type or ret_type in ("", "null_action"):
        return False
    if ret_type in SM_NORMAL_REJECTS:
        return False
    if ret_type in SM_CONTINUATION:
        return True
    return ret_type.startswith("pduSession") and (
        ret_type.endswith("Accept") or ret_type.endswith("Command") or ret_type.endswith("Reject")
    )
