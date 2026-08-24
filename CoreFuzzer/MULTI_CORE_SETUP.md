# 多核心网（Open5GS / free5GC / OAI）接入说明

ProbeFuzzer 已通过「核心网适配层」参数化，同一套代码可对三个 5G 核心网跑相同实验。
切换核心网只需设置 `CORE` 环境变量。

## 0. 适配层机制

`core_profile.py` + `core_profiles/*.yaml` 把核心网特有信息全部参数化：

| 字段 | 作用 |
|------|------|
| `deployment` | native（pgrep 检测进程）/ docker（docker ps 检测容器） |
| `processes` | amf/smf/upf 的进程名或容器名 |
| `amf_ngap_host/port` | AMF N2 地址 |
| `log_paths` | 崩溃证据日志路径 |
| `start_cmd` / `kill_cmd` | 启动/停止命令（`{VAR}` 从环境变量展开） |
| `fsm_path` / `fsm_sm_path` | 学习到的 FSM 文件 |
| `mongodb_cleanup` | 是否清理 MongoDB UE 状态（仅 Open5GS） |
| `gnb_config` | UERANSIM gNB 配置文件名（含 AMF 地址） |

已重构读取 profile 的文件：`crash_detector.py`、`setup_helper.py`、
`core_fuzzer_dueling.py`、`ground_truth_validation.py`。

Φ 预言机、FSM 逻辑、NAS 消息格式、变异、调度**未改**（NAS 层核心网无关）。

## 1. 环境变量（加入 .env）

```bash
# .env 追加
FREEGC_PATH=/home/mm/go-workspace/src/free5gc-v4.2.3
OAI_PATH=/home/mm/桌面/oai-cn5g-fed
```

## 2. 切换核心网运行

```bash
cd CoreFuzzer

# Open5GS（默认）
python3 core_fuzzer_dueling.py sample.yaml

# free5GC
CORE=free5gc python3 core_fuzzer_dueling.py sample.yaml

# OAI
CORE=oai python3 core_fuzzer_dueling.py sample.yaml
```

`setup_helper.py` 的 `startCore/startGNB/startUE` 会按 profile 自动选择启动命令和
UERANSIM 配置。

## 3. free5GC 准备

```bash
cd $FREEGC_PATH
# 编译（Go）
make  # 或 go build ./...

# 配置：默认 config/amfcfg.yaml 里 AMF NGAP = 127.0.0.18:38412（已匹配 profile）

# 启动（run.sh 会拉起所有 NF，日志写 log/free5gc.log）
sudo bash run.sh
# 停止
sudo bash force_kill.sh
```

UERANSIM 的 `free5gc-gnb.yaml`（已生成）把 AMF 地址指向 `127.0.0.18`。

## 4. OAI 准备

```bash
cd $OAI_PATH/docker-compose
# 启动基础 NFs（AMF/SMF/UPF/NRF/MySQL/MongoDB）
docker compose -f docker-compose-basic-nrf.yaml up -d
# 停止
docker compose -f docker-compose-basic-nrf.yaml down
```

容器名 `oai-amf` / `oai-smf`（已匹配 profile）。`oai-gnb.yaml`（已生成）AMF 地址
暂用 `127.0.0.1`（依赖 compose 的 `38412/sctp` 端口映射）；若 UERANSIM 无法连接，
需改成 OAI AMF 容器的 bridge IP（通常 `192.168.70.132`）。

## 5. FSM 学习（每个核心网各学一份）

FSM 是核心网相关的（状态机行为不同），需对 free5GC / OAI 分别跑 Corelearner：

```bash
cd Corelearner
# 对 free5GC（先把 Corelearner 的 core.properties 指向 free5GC 的 AMF 地址）
java -jar Corelearner.jar core.properties
# 输出 open5gs.dot / open5gs_sm.dot → 重命名放到 CoreFuzzer/fsms/free5gc*.dot
```

具体步骤：
1. 启动目标核心网（free5GC 或 OAI）+ UERANSIM。
2. 改 `core.properties` 里 AMF/gNB 地址指向目标核心网。
3. 跑 Corelearner 学习 FSM。
4. 把输出 `open5gs.dot`/`open5gs_sm.dot` 复制为 `fsms/free5gc.dot`/
   `fsms/free5gc_sm.dot`（或 `fsms/oai*.dot`）。
5. profile 的 `fsm_path`/`fsm_sm_path` 已指向对应文件。

> 注：FSM 未学之前，可临时让 free5gc/oai 的 `fsm_path` 也指向 `open5gs.dot`
> 先跑通流程，再替换为各自学到的 FSM。

## 6. 实验指标一致性

三个核心网都用同一套指标（FPR / TC / SEE / PV_Φ / ST），数据记录方式一致：

- `fuzzing_stats` / `savedFSM*.json` / `wire_phi_hits*.csv` / `crash_reports*/`
- ground-truth 混淆矩阵：`CORE=<core> python3 ground_truth_validation.py --trials 20`

## 待办（需实际运行验证）

- [ ] free5GC/OAI 的 FSM 学习（Corelearner 跑通）
- [ ] OAI AMF 容器 IP 确认（127.0.0.1 端口映射 vs 容器 bridge IP）
- [x] free5GC 进程名确认（`/free5gc/bin/amf`，容器名 `fuzzing-free5gc-amf`）
- [ ] 三个核心网的 48h 对比实验
- [ ] **free5GC 注册到 ω=R 的最后一环**：Security Mode Complete 被明文发送（见下）

## free5GC 救活记录（2026-08-23 实测）

free5GC 之前跑不通，根因是 3 个环境问题 + 若干 Open5GS 硬编码。已全部修复，fuzzer 现可跑起来、
UE 可注册、认证可通过，注册流到达 Security Mode Command。

### 环境修复（free5GC 核心网）

1. **AMF/AUSF/UDM/UDR 日志默认关闭**：`logger:` 段缺 `enable:true`。改
   `~/桌面/5g-fuzzer/src/deployment/free5gc/configs/{amf,ausf,udm,udr}cfg.yaml`
   加 `enable: true` + `reportCaller: true`，否则看不到崩溃/错误。
2. **MongoDB 挂了**：`fuzzing-free5gc-mongodb` 容器 `Exited(14)` 7 天未重启，
   导致所有 NF 注册 NRF 超时。`docker compose up -d mongodb` 重启即可。
3. **UE 订阅数据缺失**：`free5gc` 库无 `subscriptionData.authenticationData.*`。
   用 `mongosh` 直接灌，**注意 schema 是 openapi v1.2.3 的加密字段**：
   - `authenticationSubscription`：`{ueId, authenticationMethod:"5G_AKA",
     encPermanentKey:<K>, sequenceNumber:{sqn:"000000000023"},
     authenticationManagementField:"8000", encOpcKey:<OPC>}`
     （**不是** `permanentKey.permanentKeyValue` / `opc.opcValue`，否则认证 500）
   - `provisionedData.amData`：`{ueId, gpsis, subscribedUeAmbr{uplink,downlink},
     nssai{defaultSingleNssais[{sst:1,sd:"010203"}]}}`
   - `provisionedData.smfSelectionSubscriptionData`：`{ueId,
     subscribedSnssaiInfos{"010203":{dnnInfos[{dnn:"internet"}]}}}`
   - IMSI 范围：fuzzer 用 `-i imsi-999700000000001+offset`，但 SUCI 的 MCC/MNC
     取配置的 208/93，故有效 SUPI 是 `imsi-208930000000001..005000`（灌 5000 个）。
4. 重启全部 NF：`docker compose restart amf smf ausf udm udr pcf nssf`。

### fuzzer 代码修复（Open5GS 硬编码 → profile 感知）

- `core_fuzzer_dueling.py`：`check_system_ready` 里 `is_process_running("5gc")`
  改为 `_core_running()`（docker 查容器，native 查进程）。
- `setup_helper.py`：`startUE()` 补 `-p str(profile.ue_port)`，否则 UE 默认监听
  45678 而 fuzzer 连 45679（free5gc 的 ue_port）。
- `crash_detector.py`：`_read_log_tail()` 支持 docker 部署读 `docker logs`，
  `detect_amf/smf_crash` 的 `log_file=None` 解析为容器名；崩溃关键词加 `panic`/`fatal error`。
- `.env`：`MONGO_URI` 改为 `mongodb://172.17.0.2:27017`（容器内 localhost 不通，
  `probe-fuzzer-mongo` 在默认 bridge 172.17.0.2）。
- FSM 重建很慢（`get_all_paths` 全路径枚举）：若无 `savedFSM.json` 会卡几分钟。
  可 `cp savedFSM_rl_dueling.json savedFSM.json` 并把各 state 的 `oracle.state`
  重置为 `"I"` 跳过（见 memory 的污染坑）。

### 注册到 ω=R 的完整修复链（2026-08-23 已跑通）

注册失败的三层根因，逐个修：

1. **IMSI 的 MCC/MNC 不匹配 → K_AMF 派生错 → Security Mode Complete MAC 校验失败**
   （AMF 报 `Security Mode Command integrity check failed` / `wrong security header type`）。
   修：`core_profile.py` 加 `imsi_base` 字段（默认 `999700000000001`），
   `core_profiles/free5gc.yaml` 设 `imsi_base: 208930000000001`（匹配 MCC 208/MNC 93），
   `setup_helper.py` 的 `startUE` 用 `current_profile().imsi_base + IMSI_OFFSET`。
   —— fuzzer 的 `-i imsi-9997...`（MCC 999）跟 SUCI/解匿 SUPI（MCC 208）不一致，
   导致 K_SEAF/K_AMF 派生两端不一致。
2. **订阅数据缺 `servingPlmnId`**：UDR `QueryAmDataProcedure` 按
   `{ueId, servingPlmnId}` 过滤（`access_and_mobility_subscription_data_document.go:25`），
   只灌 `ueId` 会 `SDM_Get Slice Selection Subscription Data 404`。
   修：`amData` 和 `smfSelectionSubscriptionData` 都加 `servingPlmnId: "20893"`。
3. **认证订阅 schema 用加密字段**（见上文 `encPermanentKey`/`encOpcKey`）。

修完后实测：`Authentication Success → SecurityMode Success → Send Registration Accept
→ Registration Complete → ContextSetup Success → Registered`，fuzzer 侧
`✓ canonical MM prefix → Registered`、`Oracle MM ω=R`，进入模糊测试阶段（bypass seeds 正常发送）。

### UPF / SM（PDU 会话）修复

UPF 之前崩溃循环，日志 `open Gtp5g: open link: create: operation not supported`——缺
**gtp5g 内核模块**。修法（已在宿主机装好并持久化）：

```bash
git clone --depth 1 https://github.com/free5gc/gtp5g.git /tmp/gtp5g
cd /tmp/gtp5g && make && sudo make install   # install 会 cp 到 /lib/modules + 写 /etc/modules-load.d/gtp5g.conf
sudo depmod -a && sudo modprobe gtp5g
docker compose restart upf                  # 在 free5gc deployment 目录
```

修好后 UPF `UPF started`、PFCP(8805) + GTP-U(2152) 监听、SMF 建立 PFCP 关联。MM 的
NAS 模糊测试本不需要 UPF（用户面），只有 SM（PDU 会话建立/释放）需要。

## 让变异真正跑起来的两个 fuzzer 修复（核心网无关）

free5GC 首轮 200 迭代 `发送消息数=0`（变异没跑），两个根因：

1. **`db_helper.py` 的 `check_seed_msg` 阈值 `>= 21`**：某状态「有趣消息」<21 就跳过变异。
   DB 只有 199 条种子（每状态 15~19 条），全不达标。改 `>= 1` 即可进变异。
2. **`core_fuzzer_dueling.py` 的 `sendSymbol` 连接逻辑死等 "DONE" 横幅**：注册后
   `init_reg=true`，StateLearner 不再发 DONE，`recv(1024)` 5s 超时被误判「连接失败」，
   seed 收集阶段每个符号都卡死。修复：像 `connectUE` 一样容忍「无 DONE 横幅」
   （`recv` 3s 超时后继续，`settimeout(12)`）。

修完后变异生效：日志出现 `byte_mut: 1`、`energy: [...]`（PowerSchedule 调能）、
`send message` + `send probe to AMF`，`发送消息数` 正常累加。
