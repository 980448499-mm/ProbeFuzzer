# O1 判 G1 实测验证：SMF SSC 断言崩溃

对 SMF-SSC-DISALLOWED-ASSERT-ABORT 崩溃，运行 O1 探针（`crash_detector.py` 的
`detect_smf_crash`），验证其判定为 G1/REAL_CRASH。

## 方法

- 反向补丁恢复 v2.6.6 行为：注释 `open5gs/src/smf/nudm-handler.c` 330–347 行的
  SSC 拒绝逻辑（`#if 0`），使 SSC 不允许时不拒绝、继续处理。
- 5gc 以 `stdbuf -eL -oL` 行缓冲启动，确保 abort 前的 `FATAL` 日志 flush 到 core.log。
- 脚本：`verify_smf_g1.py`（在 SMF 崩溃前初始化 `CrashDetector`，记录 PID，
  触发 SSC1+SSC7，再调用 `detect_smf_crash`）。

## 实测输出

```
[O1] SMF PIDs before = [1500]
[触发] SSC1 status=201 loc=http://127.0.0.4:7777/nsmf-pdusession/v1/sm-contexts/1
[触发] SSC7 status=0 err=curl: (92) HTTP/2 stream 1 was not closed cleanly before end of the underlying stream

[O1] is_crash=True crash_type=CrashType.REAL_CRASH
[O1] log_evidence=... FATAL: smf_nudm_sdm_handle_subscription: Assertion `r != OGS_ERROR' failed. (../src/smf/nudm-handler.c:492)
[O1] smf_pids_after=[]
RESULT: O1 判 G1/REAL_CRASH ✅
```

## 崩溃日志证据（core.log）

```
18:04:35.696: [smf] ERROR: SSCMode is not allowed (../src/smf/nudm-handler.c:175)
18:04:35.697: [smf] ERROR: No Arp.preempt_cap (../src/smf/npcf-build.c:247)
18:04:35.697: [smf] FATAL: smf_nudm_sdm_handle_subscription: Assertion `r != OGS_ERROR' failed. (../src/smf/nudm-handler.c:492)
18:04:35.697: [core] FATAL: backtrace() returned 10 addresses (../lib/core/ogs-abort.c:37)
18:04:35.778: [app] ERROR: Signal-NUM[17] received (Child status change) (../src/main.c:78)
```

## O1 判 G1 的两个依据

| O1 依据 | 实测 |
|---------|------|
| 进程终止 | `smf_pids_after=[]`（SMF PID 1500 消失）|
| crash log | `FATAL: ... Assertion 'r != OGS_ERROR' failed`（含 O1 关键词 `FATAL` 和 `Assertion`）|

## 结论

O1 对 SMF SSC 断言崩溃（真实 NAS 5GSM 逻辑漏洞）判定为 **G1/REAL_CRASH**，
满足审稿人 R1「introduce a ground-truth crash and show O1 labels it G1」的要求。
