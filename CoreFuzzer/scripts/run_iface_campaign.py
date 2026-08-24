#!/usr/bin/env python3
"""Structure-aware fuzz: valid SBI/PFCP/NGAP session, then mutate inner fields."""
from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from objects.iface_probes import (  # noqa: E402
    UPF_PFCP,
    classify_ngap,
    crashed,
    gsm_nas,
    live_pids,
    load_seed,
    log_alerts,
    modify_payloads,
    mutate_after,
    n2_setup_rsp_transfer,
    ngap_reg_then_ul,
    pfcp_est_then_modify,
    pfcp_sweep_delete,
    sbi_create_sm_context,
    sbi_modify,
    sbi_modify_n2,
)

ITERS = int(os.getenv("IFACE_ITERS", "40"))
SEED = int(os.getenv("IFACE_SEED", "2"))
LOG_PATH = Path(os.getenv("CORE_LOG", str(ROOT / "logs" / "core.log")))
OUT_CSV = ROOT / "iface_hits.csv"
OUT_JSON = ROOT / "iface_campaign_results.json"

FIELDS = [
    "i",
    "iface",
    "name",
    "target",
    "mut",
    "http",
    "rx",
    "class",
    "dead",
    "log_alert",
    "interesting",
    "note",
]


def nas_off(buf: bytes) -> int:
    for m in (b"\x2e\x05\x01\xc1", b"\x7e\x00", b"\x7e\x02"):
        i = buf.find(m)
        if i >= 0:
            return i
    return min(16, max(0, len(buf) - 1))


def interesting(dead, alerts, http, cls: str) -> bool:
    if dead or alerts:
        return True
    if http >= 500 or http in (200, 201, 204):
        return True
    if "UECtxRel" in cls:
        return True
    if cls.startswith("ok:DownlinkNAS"):
        return True
    if "ok:NGSetup" in cls:
        return True
    if "DownlinkNAS" in cls or "UECtxRel" in cls:
        return True
    if "/type51" in cls or cls.endswith("type51"):
        return True
    if "/type53" in cls or cls.endswith("type53"):
        return True
    return False


def main() -> None:
    rng = random.Random(SEED)
    ROOT.joinpath("logs").mkdir(exist_ok=True)
    results = []
    n_crash = n_int = 0
    counts = {"sbi": 0, "pfcp": 0, "ngap": 0}

    print("=== structured interface campaign ===")
    print(f"  live: {{k: v for k, v in live_pids().items() if v}}".replace("{k: v for k, v in live_pids().items() if v}", str({k: v for k, v in live_pids().items() if v})))

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        i = 0

        def row(**kw):
            nonlocal i, n_crash, n_int
            i += 1
            rec = {k: kw.get(k, "") for k in FIELDS}
            rec["i"] = i
            rec["interesting"] = int(
                interesting(rec["dead"], rec["log_alert"], rec.get("http") or 0, str(rec.get("class") or ""))
            )
            if rec["dead"]:
                n_crash += 1
            if rec["interesting"]:
                n_int += 1
            w.writerow(rec)
            f.flush()
            results.append(rec)
            flag = " ***" if rec["interesting"] else ""
            print(
                f"[{i}] {rec['iface']} {rec['name']} http={rec['http']} rx={rec['rx']} "
                f"cls={rec['class']}{flag}"
            )
            return rec

        def wrap(iface, name, target, mut, fn):
            counts[iface] = counts.get(iface, 0) + 1
            before = live_pids()
            log0 = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0
            out = fn()
            time.sleep(0.12)
            after = live_pids()
            dead = ",".join(crashed(before, after))
            alerts = ",".join(log_alerts(LOG_PATH)) if LOG_PATH.exists() and LOG_PATH.stat().st_size > log0 else ""
            rec = row(
                iface=iface,
                name=name,
                target=target,
                mut=mut,
                http=out.get("http", 0),
                rx=out.get("rx", 0),
                **{"class": out.get("class", "")},
                dead=dead,
                log_alert=alerts,
                note=out.get("note", "")[:180],
            )
            return rec, out, bool(dead)

        # ----- SBI: valid create, mutate N1 SM, then modify if we got a context -----
        print("-- SBI create (valid multipart + real 5GSM) --")
        rec, created, died = wrap(
            "sbi",
            "smctx_create_valid",
            "/nsmf-pdusession/v1/sm-contexts",
            "none",
            lambda: (
                lambda r: {
                    "http": r["status"],
                    "rx": len(r.get("body") or ""),
                    "class": r.get("location") or "",
                    "note": (r.get("body") or r.get("err") or "")[:180],
                    "_raw": r,
                }
            )(sbi_create_sm_context()),
        )
        if died:
            print("stop: crash after SBI create")
        else:
            loc = (created.get("class") or created.get("_raw", {}).get("location") if False else "")
            # recover location from last row note/class
            loc = rec["class"]
            if rec["http"] not in (201, 204) or not loc:
                # still try mutate-N1-only creates
                print(f"  create did not yield context (HTTP {rec['http']}); mutating N1 SM inside valid JSON")
                for n in range(8):
                    nas = bytearray(gsm_nas())
                    if nas:
                        nas[rng.randrange(len(nas))] ^= 1 << rng.randrange(8)
                    rec2, _, died = wrap(
                        "sbi",
                        f"smctx_n1_inplace_{n}",
                        "/sm-contexts",
                        "n1_inplace",
                        lambda nas=bytes(nas): (
                            lambda r: {
                                "http": r["status"],
                                "rx": len(r.get("body") or ""),
                                "class": r.get("location") or "",
                                "note": (r.get("body") or "")[:180],
                            }
                        )(sbi_create_sm_context(nas)),
                    )
                    if died:
                        break
                    if rec2["http"] == 201 and rec2["class"]:
                        loc = rec2["class"]
                        break
            if loc and loc.startswith("http"):
                modify_url = loc if loc.endswith("/modify") else loc.rstrip("/") + "/modify"
                print(f"-- SBI N2 activate then modify {modify_url} --")
                time.sleep(1.5)
                rec_n2, _, died = wrap(
                    "sbi",
                    "smctx_n2_setup_rsp",
                    modify_url,
                    "n2_setup_rsp",
                    lambda: (
                        lambda r: {
                            "http": r["status"],
                            "rx": len(r.get("body") or ""),
                            "class": "",
                            "note": (r.get("body") or "")[:180],
                        }
                    )(sbi_modify_n2(modify_url, n2_setup_rsp_transfer())),
                )
                if died:
                    print("stop: crash after N2 activate")
                else:
                    for name, payload in modify_payloads(rng):
                        _, _, died = wrap(
                            "sbi",
                            f"smctx_mod_{name}",
                            modify_url,
                            name,
                            lambda payload=payload: (
                                lambda r: {
                                    "http": r["status"],
                                    "rx": len(r.get("body") or ""),
                                    "class": "",
                                    "note": (r.get("body") or "")[:180],
                                }
                            )(sbi_modify(modify_url, payload)),
                        )
                        if died:
                            break
                    if not died:
                        _, _, died = wrap(
                            "sbi",
                            "smctx_mod_release",
                            modify_url,
                            "release",
                            lambda: (
                                lambda r: {
                                    "http": r["status"],
                                    "rx": len(r.get("body") or ""),
                                    "class": "",
                                    "note": (r.get("body") or "")[:180],
                                }
                            )(sbi_modify(modify_url, b'{"release":true}')),
                        )

        # ----- PFCP: assoc + est (unique SEID) + Session Modification + delete -----
        print("-- PFCP est then modification --")
        sweep_ids = list(range(1, 48)) + list(range(0xA5000001, 0xA5000010))
        freed = pfcp_sweep_delete(UPF_PFCP, sweep_ids)
        print(f"  pfcp sweep deletes with reply: {freed}")
        sess = load_seed("pfcp/type_50_311.bin")
        mod_seed = load_seed("pfcp/type_52_46.bin")
        if sess and mod_seed:
            probes = [("none", mod_seed)]
            for n in range(6):
                probes.append(mutate_after(mod_seed, 16, rng))
            for n, (mut, payload) in enumerate(probes):
                seid = 0xA5000001 + n
                rec, out, died = wrap(
                    "pfcp",
                    f"est_then_mod_{n}",
                    "upf:8805",
                    mut,
                    lambda payload=payload, seid=seid: (
                        lambda a, s, m: {
                            "http": 0,
                            "rx": len(m) or len(s),
                            "class": (
                                f"assoc{len(a)}t{a[1] if a else '-'}"
                                f"/sess{len(s)}/type{s[1] if s else '-'}"
                                f"/mod{len(m)}/type{m[1] if m else '-'}"
                            ),
                            "note": (m[:24].hex() if m else (s[:24].hex() if s else "no-rx")),
                        }
                    )(*pfcp_est_then_modify(sess, payload, UPF_PFCP, seid)),
                )
                if died:
                    break

        # ----- NGAP: same SCTP assoc: Setup → InitialUE → DownlinkNAS → UplinkNAS -----
        print("-- NGAP registration then uplink NAS --")
        subprocess.call(["pkill", "-9", "-x", "nr-gnb"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        initial = load_seed("ngap/initial_ue.bin")
        for seed_name in ("ngap/ul_nas.bin", "ngap/ul_nas_sm.bin"):
            seed = load_seed(seed_name)
            if not initial or not seed:
                continue
            off = nas_off(seed)
            probes = [("none", seed)]
            for n in range(5):
                probes.append(mutate_after(seed, off, rng))
            for n, (mut, payload) in enumerate(probes):
                rec, out, died = wrap(
                    "ngap",
                    f"reg_ul_{Path(seed_name).stem}_{n}",
                    "amf:38412",
                    f"{mut}@{off}",
                    lambda payload=payload: (
                        lambda rx_s, rx_u, rx_ul: {
                            "http": 0,
                            "rx": len(rx_ul),
                            "class": (
                                f"setup={classify_ngap(rx_s)};"
                                f"ue={classify_ngap(rx_u)};"
                                f"ul={classify_ngap(rx_ul)}"
                            ),
                            "note": (
                                f"s:{rx_s[:12].hex()} u:{rx_u[:12].hex()} "
                                f"ul:{rx_ul[:12].hex()}"
                            ),
                        }
                    )(*ngap_reg_then_ul(initial, payload)),
                )
                if died:
                    break
            if died:
                break

        while i < ITERS and not n_crash:
            # pad with extra N1-inplace creates if short
            nas = bytearray(gsm_nas() or b"\x2e\x05\x01\xc1")
            nas[rng.randrange(len(nas))] ^= 1 << rng.randrange(8)
            _, _, died = wrap(
                "sbi",
                "pad_n1",
                "/sm-contexts",
                "n1_inplace",
                lambda nas=bytes(nas): (
                    lambda r: {
                        "http": r["status"],
                        "rx": len(r.get("body") or ""),
                        "class": r.get("location") or "",
                        "note": (r.get("body") or "")[:180],
                    }
                )(sbi_create_sm_context(nas)),
            )
            if died:
                break

    summary = {
        "iters_done": len(results),
        "counts": counts,
        "interesting": n_int,
        "crashes": n_crash,
        "live_end": live_pids(),
        "hits": [r for r in results if r.get("interesting")],
        "create_http": next((r["http"] for r in results if r["name"] == "smctx_create_valid"), None),
        "create_note": next((r["note"] for r in results if r["name"] == "smctx_create_valid"), None),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2))
    print("\n=== summary ===")
    print(json.dumps({k: summary[k] for k in ("iters_done", "counts", "interesting", "crashes", "create_http", "create_note")}, indent=2))


if __name__ == "__main__":
    main()
