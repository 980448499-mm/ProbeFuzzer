# ProbeFuzzer 返修实验 Runbook（第一优先级）

本文件给出三位审稿人最尖锐的三条意见对应的确定性验证实验，代码/脚本均已就绪，
只需在有 Open5GS + UERANSIM 的环境里按顺序跑一遍并记录数据。

三条意见 → 三个实验：

| 实验 | 回应审稿意见 | 目标 | 预期结果 |
|------|-------------|------|---------|
| 1 | R1-SR1（Φ 从未触发） | 让 Φ 真正触发 | PV_Φ 从 0 → >0 |
| 2 | R1-SR2（TC=0，G1 分支未验证） | 让 AMF 崩溃，O1 检出 | TC 从 0 → >0 |
| 3 | R2-Issue1（FPR 无独立 ground truth） | 5 类故障 → 混淆矩阵 | per-class precision/recall/F1 |

---

## 0. 前置准备

### 0.1 重新编译 Open5GS（已改 C 代码）

本轮改了 `open5gs/src/amf/gmm-sm.c`（故障注入：明文服务请求/注册被接受）和
`open5gs/src/amf/gmm-handler.c`（崩溃注入：magic TMSI → abort）。必须重编译：

```bash
cd /home/mm/桌面/1/ProbeFuzzer-论文提交版的代码/ProbeFuzzer-main/open5gs
ninja -C build
```

确认 `build/src/amf/open5gs-amfd` 时间戳已更新。

### 0.2 确认依赖

```bash
which 5gc nr-ue nr-gnb mongod   # 应都在 PATH
cd CoreFuzzer && cat .env        # 确认 OPEN5GS_PATH / UERANSIM_PATH 正确
```

### 0.3 环境变量传递说明

`setup_helper.py` 的 `startCore()` 用 `subprocess.Popen(["5gc", ...])` 启动，
子进程（amfd/smfd）**继承父进程环境变量**。所以故障注入 flag 只需在
**运行 fuzzer 之前 export** 即可生效。

---

## 实验 1：让 Φ 真正触发（PV_Φ > 0）

**回应**：R1-Issue1 / SR1 —— "provide worked examples of Φ returning true on an
arrived response … If Φ never fired during the runs, the paper should say so."

**原理**：`OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST=1` 让 AMF 跳过服务请求的
完整性校验，接受明文（sht=0）服务请求；fuzzer 的 bypass seed
`plain_svc_after_sec` 在 oracle 状态 R 时发送明文服务请求，Φ 判定
`serviceRequest(sht=0) → serviceAccept` 为违规。

### 步骤

```bash
cd /home/mm/桌面/1/ProbeFuzzer-论文提交版的代码/ProbeFuzzer-main/CoreFuzzer

# 1. 开启服务请求故障注入（也让注册路径故障注入生效，可选）
export OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST=1
export OGS_FAULT_ACCEPT_PLAINTEXT_REGISTRATION=1

# 2. 跑 fuzzer（RUN_BYPASS_SEEDS 默认 true，会自动发明文 seed）
python3 core_fuzzer_dueling.py sample.yaml
```

### 观察/记录

- 控制台出现 `bypass Φ (amf/plain_svc_after_sec): True` 或 `发现协议违规`。
- `fuzzing_stats['violations']` 递增。
- `wire_phi_hits_amf.csv` / `phi_violations_*.csv` 记录去重的 PV_Φ 条目。

### 预期结果

| 指标 | 之前 | 之后 |
|------|------|------|
| PV_Φ | 0 | ≥1（去重后） |

记录到论文 Table 4 的 PV_Φ 列（Dueling DQN 行）。

---

## 实验 2：让 AMF 崩溃，O1 检出（TC > 0）

**回应**：R1-Issue2 / SR2 —— "introduce at least one ground-truth crash …
show that O1 correctly labels it G1/REAL_CRASH while surrounding benign silences
are still downgraded."

两种触发方式，都验证 O1 的 G1 分支：

### 2a. 带内崩溃（审稿人 SR2 的原话场景：magic TMSI → 崩溃）

```bash
cd CoreFuzzer

# magic TMSI 值（hex）
export OGS_FAULT_CRASH_TMSI=0xDEADBEEF

python3 core_fuzzer_dueling.py sample.yaml
```

**触发条件**：AMF 收到一条 GUTI 移动身份里 `5G-S-TMSI == 0xDEADBEEF` 的注册请求
时 `abort()`（SIGABRT）。注意：现有 bypass seed 用的是 SUCI，**不是** GUTI，
所以需要一条 GUTI 注册 seed（从 UERANSIM 捕获一条真实 mobility registration
update，或见 §附：GUTI seed）。带内崩溃命中后：
- `logs/core.log` 出现 `ProbeFuzzer fault magic TMSI … abort()` 和 SIGABRT。
- fuzzer 的 `check_amf` 探针报 REAL_CRASH，`fuzzing_stats` 记录 TC 增 1。

### 2b. 外部崩溃（更简单，等价验证 G1）

直接 kill AMF 进程，然后跑探针：

```bash
# 单独验证（不跑完整 fuzzer）：
sudo python3 ground_truth_validation.py --trials 5
# 其中 "crash" 类 = kill -9 open5gs-amfd，期望 O1 分类为 G1
```

### 预期结果

| 指标 | 之前 | 之后 |
|------|------|------|
| TC | 0 | ≥1（G1 正确检出，且周围良性静默仍被降级为 G2/G3） |

---

## 实验 3：Ground-truth FPR 验证（5 类故障 → 混淆矩阵）

**回应**：R2-Issue1 —— "False-positive rate 1.9% is calculated based on oracle
reclassification and not independent ground truth. Validate it using controlled
crashes, hangs, rejections, packet loss, and network failures."

### 步骤

```bash
cd CoreFuzzer

# 需要 root（iptables / tc）
sudo python3 ground_truth_validation.py --trials 20
```

脚本会：
1. 依次注入 5 类故障（crash / hang / rejection / packet_loss / transient）；
2. 每类跑 `--trials` 次，跑 O1 探针并分类；
3. 输出混淆矩阵 + per-class precision/recall/F1 + 整体 accuracy。

### 5 类故障 → 期望分类

| 故障 | 注入方式 | ground truth | 期望 O1 分类 |
|------|---------|-------------|-------------|
| crash | `kill -9` amfd | REAL_CRASH | G1 |
| hang | `kill -STOP` amfd | HANG | G3 |
| rejection | 不合规消息 | NORMAL_REJECT | G2 |
| packet_loss | `iptables DROP` N2 端口 | NETWORK_ERROR | G4 |
| transient | `tc netem delay 3s` | TRANSIENT | G2b |

### 记录

把输出的混淆矩阵和 per-class 指标填入论文 7.3.1 的独立 ground-truth 验证段
（新增一段，区别于 O0-vs-O1 的 FPR 定义）。

---

## 数据记录模板

每个实验跑完后，把结果汇总进下表（用于 rebuttal）：

| 实验 | 审稿意见 | 之前值 | 之后值 | 证据文件 |
|------|---------|--------|--------|---------|
| 1 Φ 触发 | R1-SR1 | PV_Φ=0 | PV_Φ=__ | wire_phi_hits_amf.csv |
| 2 O1 崩溃 | R1-SR2 | TC=0 | TC=__ | crash_reports_*/confirmed/ |
| 3 ground truth | R2-Issue1 | 无独立验证 | accuracy=__ | 脚本输出混淆矩阵 |

---

## 附：GUTI 注册 seed（实验 2a 需要）

现有 `pv_probes.py` 的 seed 都是 SUCI 移动身份。带内 magic-TMSI 崩溃需要
GUTI 移动身份（TMSI = magic）。两种办法：

1. **从 UERANSIM 捕获**（推荐）：注册成功后，UE 持有 GUTI；在 UERANSIM 日志里
   找到 mobility registration update 的 NAS hex，替换 `_PLAIN_MOBILITY_REG`。
2. **手工构造**：5GS mobile identity GUTI = 类型字节 + MCC/MNC(3B) +
   AMF Region(1B) + AMF Set/Pointer(2B) + 5G-TMSI(4B)，其中 TMSI 填 magic 值。
   注意 AMF_ID 要与 Open5GS 配置的 guami 匹配，否则 AMF 找不到 UE 上下文。

（若时间紧，实验 2 用 2b 的 `kill -9` 即可满足 R1-SR2 的"ground-truth crash"
要求；2a 是更贴合审稿人原话的增强。）
