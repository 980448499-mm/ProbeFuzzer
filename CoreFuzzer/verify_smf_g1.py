#!/usr/bin/env python3
"""SMF SSC 崩溃的 O1 G1 验证。

在 SMF 崩溃前初始化 CrashDetector（记录 PID），触发 SSC1+SSC7，
再调用 detect_smf_crash 验证 O1 判 G1/REAL_CRASH。
"""
import sys
import time

sys.path.insert(0, "/corefuzzer")

from crash_detector import CrashDetector, CrashType  # noqa: E402
from objects.iface_probes import live_pids, sbi_create_sm_context  # noqa: E402

HERE = "/corefuzzer/findings/smf_ssc_disallowed_assert_abort/poc"
SSC1 = open(f"{HERE}/n1_pdu_est_ssc1.bin", "rb").read()
SSC7 = open(f"{HERE}/n1_pdu_est_ssc7.bin", "rb").read()


def main() -> int:
    before = live_pids().get("open5gs-smfd") or []
    if not before:
        print("SMF 未运行，请先启动 5gc")
        return 2

    # 1. 初始化 O1（崩溃前，记录 SMF PID）
    cd = CrashDetector(
        crash_log_dir="./crash_reports_gt",
        smf_proc="open5gs-smfd",
        deployment="native",
    )
    print(f"[O1] SMF PIDs before = {cd.smf_pids_before}")

    # 2. 触发 SSC1（合法）+ SSC7（崩溃）
    r0 = sbi_create_sm_context(SSC1)
    print(f"[触发] SSC1 status={r0.get('status')} loc={r0.get('location')}")
    r1 = sbi_create_sm_context(SSC7)
    print(f"[触发] SSC7 status={r1.get('status')} err={(r1.get('err') or '')[:90]}")

    time.sleep(1.0)

    # 3. O1 检测
    is_crash, crash_type, info = cd.detect_smf_crash([], "./logs/core.log")
    print(f"[O1] is_crash={is_crash} crash_type={crash_type}")
    print(f"[O1] log_evidence={info.get('log_evidence')}")
    print(f"[O1] smf_pids_after={info.get('smf_pids_after')}")

    if crash_type == CrashType.REAL_CRASH:
        print("RESULT: O1 判 G1/REAL_CRASH ✅")
        return 0
    print(f"RESULT: O1 判 {crash_type} ❌")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
