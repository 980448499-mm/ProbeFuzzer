#!/usr/bin/env python3
"""Re-apply L1 policy to existing wire_phi_hits CSV or fuzz log; write filtered hits."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from objects.l1_policy import HIT_CSV_FIELDS, eligible_for_l1_hit, eligible_for_oracle  # noqa: E402
from objects.log_observation import LogObserver, resolve_ret_type_with_logs  # noqa: E402
from objects.oracle import component_for_send_type, query_component_violation  # noqa: E402
from objects.oracle_amf import OracleAmf  # noqa: E402
from objects.oracle_smf import OracleSmf  # noqa: E402
from objects.wire_nas import normalize_wire_security  # noqa: E402

_VIOL_RE = re.compile(r"violation \((\w+)\):\s+True")
_INFER_RE = re.compile(r"inferred ret_type \((\w+)\): (\S+)")
_PROBE_RE = re.compile(r"^\{.*\"new_msg\"")


def rescore_csv(path: Path, out_amf: Path, out_smf: Path, out_all: Path) -> list[dict]:
    kept: list[dict] = []
    if not path.exists():
        return kept
    with path.open(encoding="utf-8-sig") as f:
        first = f.readline()
        if not first.strip() or "send_type" not in first:
            print(f"skip {path}: missing header")
            return kept
        f.seek(0)
        for row in csv.DictReader(f):
            ret_src = row.get("ret_src") or "core_log"
            gnb_error = str(row.get("gnb_error", "0")).strip() in ("1", "True", "true")
            ok, reason = eligible_for_l1_hit(
                row.get("ret_type"),
                ret_src,
                gnb_error=gnb_error,
                ret_msg=row.get("ret_msg"),
            )
            if not ok:
                print(f"  drop iter={row.get('iteration')} {row.get('send_type')} -> {row.get('ret_type')} ({reason})")
                continue
            kept.append(row)
    _write_hits(kept, out_amf, out_smf, out_all)
    return kept


def rescore_fuzz_log(log_path: Path, out_amf: Path, out_smf: Path, out_all: Path) -> list[dict]:
    """Scan fuzz log for oracle True + reconstruct rows from nearby JSON lines."""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    kept: list[dict] = []
    amf_oracle = OracleAmf()
    smf_oracle = OracleSmf()
    i = 0
    while i < len(lines):
        m = _VIOL_RE.search(lines[i])
        if not m:
            i += 1
            continue
        # Only count fuzz-loop L1 hits (reward line), not path-learning oracle checks
        if i + 1 >= len(lines) or "发现协议违规" not in lines[i + 1]:
            i += 1
            continue
        component = m.group(1)
        # Walk back for probe JSON / send_type context
        resp_json = None
        send_type = None
        state = None
        iteration = None
        ret_src = ""
        effective_ret_type = ""
        gnb_error = False
        for j in range(i - 1, max(i - 80, -1), -1):
            line = lines[j]
            if "Iter " in line and iteration is None:
                im = re.search(r"Iter (\d+)", line)
                if im:
                    iteration = im.group(1)
            if "current state:" in line and state is None:
                state = line.split("current state:")[-1].strip()
            if "send probe to" in line.lower() and send_type is None:
                pass
            im = _INFER_RE.search(line)
            if im:
                ret_src = im.group(1)
                effective_ret_type = im.group(2)
            if _PROBE_RE.match(line.strip()):
                try:
                    resp_json = json.loads(line.strip())
                except json.JSONDecodeError:
                    pass
            if "Error indication" in line:
                gnb_error = True
            if "incomingMessage" in line and send_type is None:
                sm = re.search(r"incomingMessage_(\w+)", line)
                if sm:
                    send_type = sm.group(1)
        if resp_json is None:
            i += 1
            continue
        if not send_type:
            send_type = resp_json.get("send_type") or ""
        if not send_type:
            i += 1
            continue
        if not effective_ret_type:
            effective_ret_type, ret_src = resolve_ret_type_with_logs(
                resp_json.get("ret_type"),
                resp_json.get("ret_msg"),
                include_core_log=False,
            )
        if not eligible_for_oracle(effective_ret_type, ret_src):
            i += 1
            continue
        violation = query_component_violation(
            component,
            amf_oracle,
            smf_oracle,
            send_type,
            effective_ret_type,
            resp_json.get("sht"),
            resp_json.get("secmod"),
            new_msg=resp_json.get("new_msg"),
            wire_mode=True,
        )
        if not violation:
            i += 1
            continue
        ok, reason = eligible_for_l1_hit(
            effective_ret_type,
            ret_src,
            gnb_error=gnb_error,
            ret_msg=resp_json.get("ret_msg"),
        )
        if not ok:
            print(f"  drop log iter~{iteration} {send_type} -> {effective_ret_type} ({reason})")
            i += 1
            continue
        ws, wsec, _ = normalize_wire_security(
            resp_json.get("new_msg"), resp_json.get("sht"), resp_json.get("secmod")
        )
        row = {
            "iteration": iteration or "",
            "component": component,
            "state": state or "",
            "send_type": send_type,
            "ret_type": effective_ret_type,
            "ret_src": ret_src,
            "sht": resp_json.get("sht"),
            "secmod": resp_json.get("secmod"),
            "wire_sht": ws,
            "wire_secmod": wsec,
            "byte_mut": resp_json.get("byte_mut", ""),
            "gnb_error": int(gnb_error),
            "new_msg": resp_json.get("new_msg"),
            "ret_msg": resp_json.get("ret_msg"),
        }
        kept.append(row)
        i += 1
    _write_hits(kept, out_amf, out_smf, out_all)
    return kept


def _write_hits(rows: list[dict], out_amf: Path, out_smf: Path, out_all: Path) -> None:
    for path in (out_amf, out_smf, out_all):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HIT_CSV_FIELDS)
            w.writeheader()
    for row in rows:
        comp = row.get("component") or component_for_send_type(row.get("send_type", ""))
        out = {k: row.get(k, "") for k in HIT_CSV_FIELDS}
        out["component"] = comp
        for path in (out_all, out_amf if comp == "amf" else out_smf):
            with path.open("a", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=HIT_CSV_FIELDS).writerow(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-score L1 hits with tightened policy")
    ap.add_argument("--csv", type=Path, help="Existing wire_phi_hits_*.csv")
    ap.add_argument("--log", type=Path, help="Fuzz log to rescan")
    ap.add_argument("--out-dir", type=Path, default=ROOT, help="Output directory")
    args = ap.parse_args()

    out_amf = args.out_dir / "wire_phi_hits_amf.csv"
    out_smf = args.out_dir / "wire_phi_hits_smf.csv"
    out_all = args.out_dir / "wire_phi_hits.csv"

    kept: list[dict] = []
    if args.csv:
        kept = rescore_csv(args.csv, out_amf, out_smf, out_all)
    elif args.log:
        kept = rescore_fuzz_log(args.log, out_amf, out_smf, out_all)
    else:
        for name in ("wire_phi_hits_amf.csv", "wire_phi_hits.csv"):
            p = ROOT / name
            if p.exists():
                kept.extend(rescore_csv(p, out_amf, out_smf, out_all))
                break

    print(f"L1 eligible after rescore: {len(kept)}")
    return 0 if kept else 1


if __name__ == "__main__":
    raise SystemExit(main())
