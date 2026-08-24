"""L1 hit eligibility: separate wire-Φ oracle query from CSV / replay candidates."""
from __future__ import annotations

from typing import Optional, Tuple

# Sources strong enough to drive wire-Φ oracle + L1 CSV
_STRONG_SOURCES = frozenset({"ue_json", "ret_msg_hex", "ue_log"})

# Log-only sources — diagnostic hints, never L1
_WEAK_SOURCES = frozenset({"core_log", "core_hex"})

HIT_CSV_FIELDS = (
    "iteration",
    "component",
    "state",
    "send_type",
    "ret_type",
    "ret_src",
    "sht",
    "secmod",
    "wire_sht",
    "wire_secmod",
    "byte_mut",
    "gnb_error",
    "new_msg",
    "ret_msg",
)


def eligible_for_oracle(ret_type: Optional[str], ret_src: str) -> bool:
    """Oracle may only use UE JSON, ret_msg hex, or ue.log — not core.log alone."""
    if not ret_type or not str(ret_type).strip():
        return False
    return ret_src in _STRONG_SOURCES


def eligible_for_l1_hit(
    ret_type: Optional[str],
    ret_src: str,
    *,
    gnb_error: bool = False,
    ret_msg: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    L1 CSV / replay candidate gate (stricter than oracle exploration).
    Rejects core_log-only inference and gNB semantic errors without UE downlink proof.
    """
    if not ret_type or not str(ret_type).strip():
        return False, "empty_ret_type"
    if ret_src in _WEAK_SOURCES:
        return False, "weak_source"
    if ret_src not in _STRONG_SOURCES:
        return False, f"unknown_source:{ret_src}"

    if gnb_error and ret_src != "ue_json":
        has_downlink_hex = bool(ret_msg and str(ret_msg).strip())
        if not has_downlink_hex:
            return False, "gnb_error_without_ue_downlink"

    return True, "ok"


TYPED_CSV_FIELDS = HIT_CSV_FIELDS + ("kind",)


def append_typed_response(row: dict) -> None:
    """Log every typed UE/CN observation for dual-stack replay (not only Φ hits)."""
    import csv
    from pathlib import Path

    path = Path("typed_responses.csv")
    out_row = {k: row.get(k, "") for k in TYPED_CSV_FIELDS}
    is_new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TYPED_CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(out_row)


def append_wire_phi_hit(row: dict, component: str) -> None:
    """Append one L1 hit row; always writes CSV header on empty files."""
    import csv
    from pathlib import Path

    base = Path(".")
    out_row = {k: row.get(k, "") for k in HIT_CSV_FIELDS}
    for path in (base / f"wire_phi_hits_{component}.csv", base / "wire_phi_hits.csv"):
        is_new = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HIT_CSV_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(out_row)
