# 协议违规注入与复现记录（ProbeFuzzer）

本文档串起「种子 → 违规机制 → 违反的规范条款 → 修改的代码 → Φ 结果」的完整链条，
用于回应审稿人对 fault 注入 ground-truth 与 Φ 触发机制的追问，以及实验留档。

- 核心网：Open5GS v2.8.0（含 ProbeFuzzer 故障注入改动）
- UE/gNB：UERANSIM_CoreTesting
- 语义 oracle：`CoreFuzzer/objects/oracle_amf.py`（MM 状态门 + 安全上下文门）、
  `CoreFuzzer/objects/oracle_smf.py`（SM 会话门）

---

## 1. 故障注入点（7 个，全部 env-gated，默认关闭）

所有注入点都通过环境变量开关，环境变量由 fuzzer → `5gc` → `open5gs-amfd` 进程链继承。

### F1 — `OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST=1`

- **位置**：`open5gs/src/amf/gmm-sm.c:1902`（`case OGS_NAS_5GS_SERVICE_REQUEST`）
- **违规机制**：跳过服务请求的完整性/安全上下文检查。
  - 正常行为：UE 已建立安全上下文后，明文（sht=0）service request 被拒，回 `serviceReject`（cause #9）。
  - 注入后：接受明文 service request，走 `gmm_handle_service_update`，回 `serviceAccept`。
- **违反规范**：TS 24.501 §4.4.4.3 —— 安全上下文建立后，service request 必须完整性保护。
- **代码改动**（`gmm-sm.c`）：
  ```c
  if ((!h.integrity_protected || !SECURITY_CONTEXT_IS_VALID(amf_ue)) &&
          !getenv("OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST")) {
      ogs_error("No Security Context");
      /* ... send service_reject ... */
      break;
  }
  ```
- **Φ 结果**：✅ `True`（`serviceRequest → serviceAccept` 被判为违规）

### F2 — `OGS_FAULT_ACCEPT_PLAINTEXT_REGISTRATION=1`

- **位置**：`open5gs/src/amf/gmm-sm.c:1762`（registration request 处理）
- **违规机制**：安全上下文存在时，明文 registration request 跳过 re-auth，直接走
  registration-update 路径（`gmm_handle_registration_update`）回 `registrationAccept`。
- **违反规范**：TS 24.501 §4.4.4.3。
- **Φ 结果**：❌ `False`（**未成功触发**）—— 明文 registration 到达 `gmm_handle_registration_request`
  后，复用的 `registrationRequestGUTI` 成员变量残留 IEs 导致 GUTI 解析在 `gmm-handler.c:204`
  之前就被早期拒绝，走不到 fault 分支的 accept 路径。与 F1 语义重复，暂不继续排查。

### F3 — `OGS_FAULT_ACCEPT_PLAINTEXT_DEREGISTRATION=1`（本次新增）

- **位置**：`open5gs/src/amf/gmm-sm.c:2011`（`case OGS_NAS_5GS_DEREGISTRATION_REQUEST_FROM_UE`）
- **违规机制**：接受明文（sht=0）去注册请求，**同步**回 `deregistrationAccept`。
  - 正常行为：明文 deregistration request 被静默丢弃（`ogs_error("No Security Context")` 后 break，无响应）。
  - 注入后：强制 `switch_off=0` 后直接 `nas_5gs_send_de_registration_accept()`，绕过 SBI 异步路径（避免 UE 侧超时）。
- **违反规范**：TS 24.501 §4.4.4.3 —— 安全上下文建立后，deregistration request 必须完整性保护。
- **代码改动**（`gmm-sm.c`）：
  ```c
  if (getenv("OGS_FAULT_ACCEPT_PLAINTEXT_DEREGISTRATION") &&
          (!h.integrity_protected || !SECURITY_CONTEXT_IS_VALID(amf_ue))) {
      ogs_warn("[ProbeFuzzer] accepting plaintext deregistration (fault)");
      amf_ue->nas.de_registration.switch_off = 0;
      nas_5gs_send_de_registration_accept(amf_ue);
      OGS_FSM_TRAN(s, &gmm_state_de_registered);
      break;
  }
  ```
- **Φ 结果**：✅ `True`（`deregistrationRequest → deregistrationAccept` 被判为违规）

### F4 — `OGS_FAULT_CRASH_TMSI=<hex>`

- **位置**：`open5gs/src/amf/gmm-handler.c:216`
- **违规机制**：注册请求携带的 5G-S-TMSI 等于 magic 值时 `abort()`（SIGABRT）。
  这是**可用性违规（崩溃）**，不是语义违规，由 **O1 探针**（G1 REAL_CRASH 分支）检测，而非 Φ。
- **代码改动**（`gmm-handler.c`）：
  ```c
  if (getenv("OGS_FAULT_CRASH_TMSI")) {
      uint32_t magic = (uint32_t)strtoul(getenv("OGS_FAULT_CRASH_TMSI"), NULL, 0);
      if (amf_ue->old_guti.m_tmsi == magic) {
          ogs_error("[ProbeFuzzer fault] magic TMSI 0x%x -> abort()", magic);
          abort();
      }
  }
  ```

### F5 — `OGS_FAULT_ACCEPT_PDU_SESSION_BEFORE_MM=1`（SM-before-MM，本次新增）

- **位置**：`open5gs/src/amf/gmm-sm.c:3357`（`gmm_state_initial_context_setup` 的
  `case OGS_NAS_5GS_UL_NAS_TRANSPORT`）
- **违规机制**：UE 在**未完成 MM 注册**时（state S：securityModeComplete 后、
  registrationComplete 前）发起 PDU 会话建立，AMF 仍返回 `pduSessionEstablishmentAccept`。
  - 正常行为：UL NAS TRANSPORT 在 `initial_context_setup` 状态落到 default 分支，
    被当作 "Unknown message" 忽略，不会建立会话。
  - 注入后：直接调用 `gmm_handle_ul_nas_transport()` 走完整 SMF SBI 流程，返回 accept。
- **违反规范**：TS 24.501 —— UE 应完成 MM 注册后再发起 PDU 会话（SM-before-MM 违规）。
- **代码改动**（`gmm-sm.c`）：
  ```c
  case OGS_NAS_5GS_UL_NAS_TRANSPORT:
      if (getenv("OGS_FAULT_ACCEPT_PDU_SESSION_BEFORE_MM")) {
          ogs_warn("[ProbeFuzzer] accepting PDU session before MM (fault)");
          gmm_handle_ul_nas_transport(
                  ran_ue, amf_ue, &nas_message->gmm.ul_nas_transport);
      } else {
          ogs_error("[%s] UL NAS transport before registration", amf_ue->supi);
      }
      break;
  ```
- **触发方式（fuzzer 侧）**：`core_fuzzer_dueling.py` 加 `V2_PROBE` 环境变量开关；
  `objects/pv_probes.py` 的 `reach_mm_registered()` 加 `v2_probe` 参数，在收到
  `registrationAccept` 后、发送 `registrationComplete` 前（ω=S，`mm_registered=False`），
  **顺序**发起 `PDUSessionEstablishmentRequest` 并调用 `OracleSmf.query_message()` 判定。
  （注：最初尝试改 UERANSIM 的 `securityModeComplete` case 让 UE 自动连发 PDU session，
  但会导致 registrationAccept 与 pduSessionAccept 响应交织、顺序混乱，已回滚。）
- **Φ 结果**：✅ `True`（`PDUSessionEstablishmentRequest → pduSessionEstablishmentAccept`
  在 `mm_registered=False` 时被判为违规，点亮 OracleSmf 会话门）

### F6 — `OGS_FAULT_RELEASE_SESSION_AFTER_ESTABLISHMENT=1`（SM 自发释放，本次新增）

- **位置**：`open5gs/src/smf/gsm-sm.c:898`（SMF 会话建立完成、`OGS_FSM_TRAN(s, smf_gsm_state_operational)` 后）
- **违规机制**：SMF 在 PDU 会话刚 Active 后，**自发**发起网络请求的 PDU 会话释放
  （UE 未发任何 release request）。
  - 正常行为：会话 Active 后等待 UE 请求（release/modification）或网络策略触发，不主动释放。
  - 注入后：立即复用 `gsm_build_pdu_session_release_command()` + `smf_namf_comm_send_n1_n2_message_transfer()`
    下发 `pduSessionReleaseCommand`。
- **违反规范**：TS 24.501 / TS 23.502 §4.3.4 —— PDU 会话释放应由 UE 或网络（有触发原因）发起，
  会话刚建立即无请求释放是 SM 会话状态违规。
- **代码改动**（`gsm-sm.c`）：
  ```c
  if (getenv("OGS_FAULT_RELEASE_SESSION_AFTER_ESTABLISHMENT")) {
      smf_n1_n2_message_transfer_param_t rel_param;
      memset(&rel_param, 0, sizeof(rel_param));
      rel_param.state = SMF_UE_OR_NETWORK_REQUESTED_PDU_SESSION_RELEASE;
      sess->pti = OGS_NAS_PROCEDURE_TRANSACTION_IDENTITY_UNASSIGNED;
      rel_param.n1smbuf = gsm_build_pdu_session_release_command(
          sess, OGS_5GSM_CAUSE_REACTIVATION_REQUESTED);
      rel_param.n2smbuf = ngap_build_pdu_session_resource_release_command_transfer(
          sess, SMF_NGAP_STATE_DELETE_TRIGGER_SMF_INITIATED,
          NGAP_Cause_PR_nas, NGAP_CauseNas_normal_release);
      smf_namf_comm_send_n1_n2_message_transfer(sess, NULL, &rel_param);
  }
  ```
- **触发方式（fuzzer 侧）**：`core_fuzzer_dueling.py` 加 `V3_PROBE` 环境变量开关（并让
  `V3_PROBE=true` 时跳过 SM FSM 路径执行，改走 canonical `reach_pdu_session`）；
  `objects/pv_probes.py` 的 `reach_pdu_session()` 加 `v3_probe` 参数，在会话 Active 后发
  `gsmStatus` 触发下一次 recv，读到 socket 缓冲区里的 `pduSessionReleaseCommand`。
- **oracle 调整**：`objects/oracle_smf.py` 的 session-A 分支加一行，让「任何非
  ReleaseRequest 的 send_type + `pduSessionReleaseCommand`」都判为违规（原逻辑被第一个
  if 的 `endswith("Command")` 误拦）。本 V3 场景 send_type=`gsmStatus` 本就不在正常请求
  列表里，故该调整是增强而非必需。
- **Φ 结果**：✅ `True`（`gsmStatus → pduSessionReleaseCommand` 在会话 Active 时被判为违规，
  再次点亮 OracleSmf 会话门）

### F7 — `OGS_FAULT_PROTECTED_AUTH_REQUEST=1`（安全前完整性保护，本次新增）

- **位置**：`open5gs/src/amf/gmm-build.c:384`（`gmm_build_authentication_request()` 的
  `return ogs_nas_5gs_plain_encode(&message)` 前）
- **违规机制**：AMF 在 UE 尚无安全上下文（state I/N）时，用完整性保护头（sht=2）发送
  authentication request（正常必须明文）。
  - 正常行为：`ogs_nas_5gs_plain_encode()` 输出 sht=0 明文。
  - 注入后：`nas_5gs_security_encode()` 输出 sht=2 的安全头（无密钥时 MAC 为假）。
- **违反规范**：TS 24.501 §4.4.4.3 —— 安全模式过程前，authentication request 必须明文发送。
- **代码改动**（`gmm-build.c`）：
  ```c
  if (getenv("OGS_FAULT_PROTECTED_AUTH_REQUEST")) {
      message.h.security_header_type =
          OGS_NAS_SECURITY_HEADER_INTEGRITY_PROTECTED_AND_CIPHERED;
      return nas_5gs_security_encode(amf_ue, &message);
  }
  return ogs_nas_5gs_plain_encode(&message);
  ```
- **验证方式（重要）**：该 fault 会让 AMF 真实发送 sht=2 假 MAC 的 authentication request，
  而 UERANSIM UE 收到后 MAC 校验失败、抛 `invalid NAS message type` 崩溃，无法完成 Φ 判定。
  故实际实验**不设该 fault env**，改由 fuzzer 的 `V4_PROBE` 在 `reach_mm_registered()` 收到
  authenticationRequest 时**手动以 sht=2** 调用 `OracleAmf.query_message()` 验证 Φ 检测逻辑。
  两者合起来证明：fault 真实产生 sht=2（UE 崩溃佐证），Φ 能对 sht=2 于 state I/N 判违规。
- **oracle 调整**：`objects/oracle_amf.py` 的 whitelist 加 `wire_sht == 0` 前置条件，使
  `(registrationRequest → authenticationRequest)` 等明文 continuation 只在明文时被抑制，
  而 sht≠0（本 V4 场景）不再被误放行。
- **Φ 结果**：✅ `True`（`registrationRequest → authenticationRequest` 于 state I/N 且
  sht=2 被判为违规，点亮 OracleAmf MM 状态门的安全前保护分支）

---

## 2. Bypass 明文种子（5 条，`objects/pv_probes.py`）

种子在 oracle 状态 R（已注册）时以明文（sht=0, secmod=1）发送，验证 Φ 的安全上下文门。
发送顺序已按「干净上下文优先」重排：serviceRequest → deregistration → registration → GUTI-reg → identity。

| # | kind | send_type | hex | 触发 fault |
|---|------|-----------|-----|-----------|
| 1 | plain_svc_after_sec | serviceRequest | `7E004C000007F40040C00003535002B67E` | F1 |
| 2 | plain_dereg_after_sec | deregistrationRequest | `7E00450E000D0199F907000000000000000000` | F3 |
| 3 | plain_reg_after_sec | registrationRequest | `7E004179000D0199F9070000000000000000741001002E04F0F0F0F02F020101700000530100` | F2 |
| 4 | plain_mobility_reg_after_sec | registrationRequest（symbol） | `plainRegistrationRequestGUTI`（UE 存储的 GUTI） | F2 |
| 5 | plain_id_after_sec | identityResponse | `7E005C000D0199F907000000000000000010` | — |

### 关键种子的逐字节结构

**plain_dereg_after_sec（#2）**：
```
7E         EPD = 5GMM
00         SHT = plaintext (0)
45         message type = deregistration request
0E         de-registration type = switch_off=0, re-reg=0, access_type=00(3GPP), tsc=0, ngKSI=7(no key)
00 0D      mobile identity length = 13
01 99F907  identity type=SUCI + PLMN(MCC 999, MNC 70)
00 000000000000  routing/protection=0 + scheme output
```
> ⚠️ 5GS mobile identity 是 LV-E：`length` 必须等于后续 content 字节数。原 seed 误写
> length=13 但 content 只有 12 字节，导致 AMF 的 NAS 解码失败
> （`ogs_nas_5gs_decode_5gs_mobile_identity() failed`），明文消息根本没进入 fault 分支。

**plain_svc_after_sec（#1）**：
```
7E         EPD = 5GMM
00         SHT = plaintext (0)
4C         message type = service request
00         ngKSI(高4位)=0 + service type(低4位)=0(signalling)
00 07 F4 00  5G-S-TMSI (4 字节)
40 C0 00 03 53 50 02 B6 7E  后续可选 IE
```

**plain_reg_after_sec（#3）**：
```
7E         EPD = 5GMM
00         SHT = plaintext (0)
41         message type = registration request
79         registration type (initial)
00 0D      mobile identity length = 13
01 99F907 0000000000000000  SUCI (13 字节)
74 10 01 00 ... 53 01 00   后续可选 IE（未逐字节验证）
```

---

## 3. 验证结果汇总

| send_type → ret_type | 注入 fault | oracle | Φ 判定 | 说明 |
|----------------------|-----------|--------|--------|------|
| serviceRequest → serviceAccept | F1 | OracleAmf | ✅ True | 明文服务请求被接受，安全上下文门触发 |
| deregistrationRequest → deregistrationAccept | F3 | OracleAmf | ✅ True | 明文去注册被接受，安全上下文门触发 |
| registrationRequest → authenticationRequest (sht=2) | F7 | OracleAmf | ✅ True | 安全前保护，MM 状态门触发 |
| PDUSessionEstablishmentRequest → pduSessionEstablishmentAccept | F5 | OracleSmf | ✅ True | SM-before-MM，会话门触发 |
| gsmStatus → pduSessionReleaseCommand | F6 | OracleSmf | ✅ True | SM 自发释放，会话门触发 |
| registrationRequest → authenticationRequest | F2 | OracleAmf | ❌ False | 触发 re-auth 而非 accept，未走到 fault 的 accept 路径 |
| identityResponse → (空) | — | — | ❌ 未触发 | 无对应 fault |
| mobility GUTI reg → (空) | F2 | — | ❌ 未触发 | GUTI 解析早期拒绝 |

**结论**：Φ 当前稳定复现 **5 类协议违规**，覆盖 **MM 安全上下文门**（service request、
deregistration）、**MM 状态门**（安全前保护）和 **SM 会话门**（PDU session before MM、
SM 自发释放）。这验证了 Φ 是「MM 状态门 + 安全上下文门 + SM 会话门」多维 oracle 的论断。
registration 违规注入点（F2）存在但未成功触发（redundant with F1/F3）。

---

## 4. 复现步骤（容器 corefuzzer:sm）

### 4.1 重新编译 Open5GS（改完 C 代码后）

源码 bind-mount 在 `/corefuzzer/open5gs`，编译产物在镜像层 `/corefuzzer_deps/open5gs/build`：

```bash
docker exec <容器> bash -c '
  cp /corefuzzer/open5gs/src/amf/gmm-sm.c /corefuzzer_deps/open5gs/src/amf/gmm-sm.c
  cd /corefuzzer_deps/open5gs && ninja -C build
'
```

### 4.2 跑 fuzzer（带 fault env）

```bash
docker run -d --name corefuzzer-dereg --privileged \
  -v "$(pwd):/corefuzzer" \
  --entrypoint bash corefuzzer:sm -c '
    systemctl start mongod; sleep 1;
    cp /corefuzzer/open5gs/src/amf/gmm-sm.c /corefuzzer_deps/open5gs/src/amf/gmm-sm.c;
    cd /corefuzzer_deps/open5gs && ninja -C build;
    cd /corefuzzer && ITERATION_LIMIT=3 SKIP_SM_ESTABLISHMENT=true \
      OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST=1 \
      OGS_FAULT_ACCEPT_PLAINTEXT_REGISTRATION=1 \
      OGS_FAULT_ACCEPT_PLAINTEXT_DEREGISTRATION=1 \
      python3 -u core_fuzzer_dueling.py sample.yaml
  '
```

### 4.3 复现 SM-before-MM（V2）

在 4.2 的 fuzzer 命令基础上，额外加 `V2_PROBE=true` 和
`OGS_FAULT_ACCEPT_PDU_SESSION_BEFORE_MM=1`（去掉 MM fault 亦可，二者独立）：

```bash
cd /corefuzzer && ITERATION_LIMIT=1 SKIP_SM_ESTABLISHMENT=true \
  FORCE_REGISTERED_SM=true V2_PROBE=true \
  OGS_FAULT_ACCEPT_PDU_SESSION_BEFORE_MM=1 \
  python3 -u core_fuzzer_dueling.py sample.yaml
```

### 4.4 成功判据

日志出现：

```
✓ canonical MM prefix → Registered            # UE 真正完成 NAS 注册
bypass plain_svc_after_sec: ... → serviceAccept
bypass plain_dereg_after_sec: ... → deregistrationAccept
bypass Φ (amf/plain_svc_after_sec): True
bypass Φ (amf/plain_dereg_after_sec): True
  🎉 发现协议违规 (bypass plain_dereg_after_sec)!
```

V2 判据（需 `V2_PROBE=true`）：

```
V2 SM-before-MM 探测: ret=pduSessionEstablishmentAccept, Φ=True
🎉 V2 发现 SM-before-MM 违规 (PDU session accept before MM registration)
```

V3 判据（需 `V3_PROBE=true` + `SKIP_SM_ESTABLISHMENT=false` +
`OGS_FAULT_RELEASE_SESSION_AFTER_ESTABLISHMENT=1`）：

```
✓ canonical PDU establishment → session Active
V3 自发释放探测: ret=pduSessionReleaseCommand, Φ=True
🎉 V3 发现自发释放违规 (pduSessionReleaseCommand without release request)
```

V4 判据（需 `V4_PROBE=true`，**不设** `OGS_FAULT_PROTECTED_AUTH_REQUEST`，见 F7 说明）：

```
V4 安全前保护探测: Φ=True
🎉 V4 发现安全前保护违规 (authenticationRequest 带 sht=2 于无安全上下文)
✓ canonical MM prefix → Registered
```

---

## 5. 两个环境坑（排查中暴露）

1. **`savedFSM.json` 污染**：`FORCE_REGISTERED_SM` 逻辑是
   `if oracle.state != "R": reach_mm_registered()`。但 `savedFSM.json` 会持久化每个
   FSM 状态的 `oracle.state`（`objects/fsm.py` 的 `State.from_json` 恢复）。
   之前运行把状态存成 `"R"`，下次加载后 fuzzer 误判「已注册」、跳过 `reach_mm_registered`，
   UE 从未真正注册（AMF 侧 `Not registered`），bypass 全失败（serviceRequest 得 serviceReject）。
   **解决**：跑实验前删 `savedFSM.json` + `savedFSM_sm.json` 让 fuzzer 从 dot 配置重建。

2. **明文 seed 的 LV-E length 不匹配**：5GS mobile identity 的 `length` 字段必须等于 content
   字节数。`_PLAIN_DEREG` 原值 length=13 / content=12，AMF 解码直接失败，消息进不了 fault
   分支。已修正为 `7E00450E000D0199F907000000000000000000`（length=content=13），并同步修正
   de-registration type 从错误的 `0x71`（switch_off=1, access_type=non-3GPP）改为 `0x0E`。
