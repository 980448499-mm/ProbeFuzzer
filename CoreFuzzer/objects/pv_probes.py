"""Canonical MM/SM prefixes and constructed NAS bypass seeds."""
from __future__ import annotations

import json
import time
from typing import Callable, Optional, Tuple

SendFn = Callable[..., str]

CONTINUATION_RETS = frozenset(
    {
        "authenticationRequest",
        "authenticationResult",
        "securityModeCommand",
        "registrationAccept",
        "configurationUpdateCommand",
        "identityRequest",
        "serviceAccept",
        "deregistrationAccept",
        "pduSessionEstablishmentAccept",
        "pduSessionModificationCommand",
        "pduSessionReleaseCommand",
        "dlNasTransport",
    }
)
REJECT_RETS = frozenset(
    {
        "registrationReject",
        "authenticationReject",
        "serviceReject",
        "securityModeReject",
        "pduSessionEstablishmentReject",
        "pduSessionModificationReject",
        "pduSessionReleaseReject",
        "gmmStatus",
        "gsmStatus",
    }
)

# Plaintext 5GMM PDUs (SHT=0) captured from UERANSIM Open5GS templates
_PLAIN_REG = (
    "7E004179000D0199F9070000000000000000741001002E04F0F0F0F02F020101700000530100"
)
# Mobility-registration-updating variant with a 5G-GUTI mobile identity.
# 结构（配合 OGS_FAULT_ACCEPT_PLAINTEXT_REGISTRATION 走 registration-update 路径）:
#   7E 00 41 = EPD + SHT(plain) + message type
#   7A       = 5GS registration type (mobility updating)
#   000B     = mobile identity length (11)
#   02       = identity type (5G-GUTI)
#   99F907   = PLMN (MCC 999, MNC 70)
#   020100   = AMF ID (region 2, set 1, pointer 0)
#   00000001 = 5G-TMSI
_PLAIN_MOBILITY_GUTI_REG = "7E00417A000B0299F90702010000000001"

# SUCI 身份版本（保留用于对比；SUCI 在 registration-update 路径下不被接受）
_PLAIN_MOBILITY_REG = (
    "7E00417A000D0199F9070000000000000000741001002E04F0F0F0F02F020101700000530100"
)
_PLAIN_SVC = "7E004C000007F40040C00003535002B67E"
_PLAIN_ID = "7E005C000D0199F907000000000000000010"
# Plaintext deregistration request (message type 0x45). Structure:
#   7E 00 45 = EPD + SHT(plain) + message type
#   0E       = de-registration type (switch_off=0, 3GPP access, ngKSI=no key)
#   000D 01 99F9... = mobile identity (LV-E, SUCI; length must equal content)
_PLAIN_DEREG = "7E00450E000D0199F907000000000000000000"

BYPASS_SEEDS = (
    # 服务请求必须最先发：它是 Φ 最干净的触发器（无 "initial registration" 例外）。
    # 去注册其次：它也需要 UE 处于已注册（R）状态才能命中 fault 注入点，
    # 且会真正去注册 UE（破坏后续上下文）。registrationRequest 会触发 re-auth，
    # 必须放在去注册之后，否则破坏后续 seed 的已注册上下文。
    {
        "kind": "plain_svc_after_sec",
        "send_type": "serviceRequest",
        "hex": _PLAIN_SVC,
        "secmod": 1,
        "sht": 0,
    },
    {
        "kind": "plain_dereg_after_sec",
        "send_type": "deregistrationRequest",
        "hex": _PLAIN_DEREG,
        "secmod": 1,
        "sht": 0,
    },
    {
        "kind": "plain_reg_after_sec",
        "send_type": "registrationRequest",
        "hex": _PLAIN_REG,
        "secmod": 1,
        "sht": 0,
    },
    {
        "kind": "plain_mobility_reg_after_sec",
        "send_type": "registrationRequest",
        "symbol": "plainRegistrationRequestGUTI",
        "secmod": 1,
        "sht": 0,
    },
    {
        "kind": "plain_id_after_sec",
        "send_type": "identityResponse",
        "hex": _PLAIN_ID,
        "secmod": 1,
        "sht": 0,
    },
)


def parse_ue_ret(out: Optional[str]) -> str:
    if not out:
        return ""
    s = str(out).strip()
    if not s or s == "null_action":
        return ""
    if s.startswith("{"):
        try:
            j = json.loads(s)
        except json.JSONDecodeError:
            return ""
        return str(j.get("ret_type") or "").strip()
    return s.split("\n")[0].strip()


def semantic_divergence(a: str, b: str) -> bool:
    """True if one stack continues a procedure and the other rejects it."""
    if not a or not b:
        return False
    return (a in CONTINUATION_RETS and b in REJECT_RETS) or (
        b in CONTINUATION_RETS and a in REJECT_RETS
    )


def reach_mm_registered(
    send_symbol: SendFn,
    oracle_amf,
    oracle_smf=None,
    v2_probe: bool = False,
    v4_probe: bool = False,
) -> bool:
    """Drive a standard registration until ω=R. Returns True on success."""
    # UE 的 RRC 建立可能很慢（容器内实测 ~20s+），重试 registrationRequest 直到 UE 就绪。
    # 每次 send_symbol 内部有 2 次尝试(各 5s 超时) ≈ 10s，重试 6 次上限 ~60s。
    ret = ""
    for _ in range(6):
        ret = parse_ue_ret(send_symbol("registrationRequest", control=True))
        if ret:
            break
        time.sleep(1.0)
    time.sleep(0.35)
    if ret == "identityRequest":
        ret = parse_ue_ret(send_symbol("identityResponse", control=True))
        time.sleep(0.35)
    if ret == "authenticationRequest":
        # [ProbeFuzzer V4] fault 让 authenticationRequest 带 sht=2（无安全上下文时），
        # 违反 TS 24.501 §4.4.4.3（安全模式前必须明文）。手动以 sht=2 判定 MM 状态门。
        if v4_probe:
            v4_viol = oracle_amf.query_message(
                "registrationRequest",
                "authenticationRequest",
                2,
                1,
                new_msg=None,
                wire_mode=True,
            )
            print(f"  V4 安全前保护探测: Φ={v4_viol}")
            if v4_viol:
                print(
                    "  🎉 V4 发现安全前保护违规 "
                    "(authenticationRequest 带 sht=2 于无安全上下文)"
                )
        ret = parse_ue_ret(send_symbol("authenticationResponse", control=True))
        time.sleep(0.35)
    if ret == "securityModeCommand":
        ret = parse_ue_ret(send_symbol("securityModeComplete", control=True))
        time.sleep(0.35)
    if ret in ("registrationAccept", "configurationUpdateCommand"):
        # [ProbeFuzzer V2] 在发 registrationComplete 之前（ω=S，mm_registered=False），
        # 顺序发起 PDU 会话建立，验证 SM-before-MM 违规（OracleSmf）。
        if v2_probe and oracle_smf is not None:
            pdu_ret = parse_ue_ret(
                send_symbol("PDUSessionEstablishmentRequest", control=True)
            )
            time.sleep(0.4)
            if pdu_ret:
                v2_viol = oracle_smf.query_message(
                    "PDUSessionEstablishmentRequest",
                    pdu_ret,
                    0,
                    1,
                    new_msg=None,
                    wire_mode=True,
                )
                print(f"  V2 SM-before-MM 探测: ret={pdu_ret}, Φ={v2_viol}")
                if v2_viol:
                    print(
                        "  🎉 V2 发现 SM-before-MM 违规 "
                        "(PDU session accept before MM registration)"
                    )
        parse_ue_ret(send_symbol("registrationComplete", control=True))
        time.sleep(0.25)
        oracle_amf.state = "R"
        print("  ✓ canonical MM prefix → Registered")
        return True
    print(f"  ✗ canonical MM prefix failed, last ret={ret or '(empty)'}")
    return oracle_amf.state == "R"


def reach_pdu_session(
    send_symbol: SendFn,
    oracle_smf,
    v3_probe: bool = False,
) -> bool:
    out = send_symbol("PDUSessionEstablishmentRequest", control=True)
    time.sleep(0.4)
    ret = parse_ue_ret(out)
    if ret == "pduSessionEstablishmentAccept":
        oracle_smf.session_state = "A"
        oracle_smf.set_mm_registered(True)
        print("  ✓ canonical PDU establishment → session Active")
        if v3_probe:
            # [ProbeFuzzer V3] SMF 在会话 Active 后自发释放（fault），UE 收到
            # accept 后又在 socket 缓冲区里收到 pduSessionReleaseCommand。
            # 发 gsmStatus 触发下一次 recv，读到缓冲区的 release command。
            rel_ret = parse_ue_ret(send_symbol("gsmStatus", control=True))
            time.sleep(0.4)
            if rel_ret:
                v3_viol = oracle_smf.query_message(
                    "gsmStatus",
                    rel_ret,
                    0,
                    1,
                    new_msg=None,
                    wire_mode=True,
                )
                print(f"  V3 自发释放探测: ret={rel_ret}, Φ={v3_viol}")
                if v3_viol:
                    print(
                        "  🎉 V3 发现自发释放违规 "
                        "(pduSessionReleaseCommand without release request)"
                    )
        return True
    print(f"  ✗ PDU establishment last ret={ret or '(empty)'}")
    return oracle_smf.session_state == "A"


def run_bypass_seeds(
    send_symbol: SendFn,
    *,
    mm_state: str,
) -> list:
    """After security context (S/R), send plaintext NAS and return observations."""
    if mm_state not in ("S", "R"):
        return []
    rows = []
    for seed in BYPASS_SEEDS:
        print(f"  bypass {seed['kind']}: {seed['send_type']} SHT={seed['sht']}")
        try:
            if "symbol" in seed:
                # 用 symbol 通道（如 plainRegistrationRequestGUTI），使用 UE 存储的 GUTI
                out = send_symbol(seed["symbol"], control=True)
                new_msg = ""
            else:
                payload = f"{seed['hex']}:{seed['secmod']}:{seed['sht']}"
                out = send_symbol("testMessage:" + payload, control=True)
                new_msg = seed["hex"]
        except Exception as e:
            print(f"    bypass send failed: {e}")
            continue
        ret = parse_ue_ret(out)
        print(f"    → {ret or '(empty)'}")
        rows.append(
            {
                "kind": seed["kind"],
                "send_type": seed["send_type"],
                "ret_type": ret,
                "new_msg": new_msg,
                "sht": seed["sht"],
                "secmod": seed["secmod"],
                "raw": out,
            }
        )
        time.sleep(0.25)
    return rows
