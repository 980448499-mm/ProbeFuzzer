# ProbeFuzzer-RL 项目结构说明

## 项目概述

ProbeFuzzer-RL 是一个基于强化学习的5G核心网模糊测试工具，通过集成Deep Q-Network (DQN)来智能选择测试状态，提高漏洞发现效率。

---

## 目录结构

```
ProbeFuzzer-main/
│
├── README.md                          # 项目主说明文档
├── LICENSE                            # 项目许可证
├── PROJECT_STRUCTURE.md              # 本文件：项目结构说明
│
├── docs/                             # 📚 文档目录
│   ├── INDEX.md                      # 文档索引
│   ├── QUICK_REFERENCE.md            # 快速参考指南
│   ├── RL_COREFUZZER_README.md       # RL-CoreFuzzer概述
│   ├── ALGORITHM_AND_WORKFLOW_GUIDE.md   # 算法与工作流程详解
│   ├── ONLINE_LEARNING_EXPLANATION.md    # 在线学习机制说明
│   ├── WHY_REINFORCEMENT_LEARNING.md     # 使用RL的优势分析
│   ├── DETAILED_EXECUTION_GUIDE.md       # 详细执行指南
│   ├── CODE_REVIEW_REPORT.md             # 代码审查报告
│   ├── PROJECT_FINAL_REPORT.md           # 项目最终报告
│   ├── RL_INTEGRATION_GUIDE.md           # RL集成指南
│   └── EXPERIMENT_ANALYSIS.md            # 实验结果分析
│
├── CoreFuzzer/                       # 🎯 核心模糊测试器
│   ├── core_fuzzer.py                # 主程序（集成RL调度器）
│   ├── rl_scheduler.py               # RL调度器（DQN实现）
│   ├── fsm_helper.py                 # 有限状态机辅助函数
│   ├── db_helper.py                  # 数据库操作辅助函数
│   ├── setup_helper.py               # 环境设置辅助函数
│   │
│   ├── objects/                      # 核心对象定义
│   │   ├── __init__.py
│   │   ├── fsm.py                    # FSM类定义
│   │   ├── graph.py                  # 图结构类
│   │   ├── oracle.py                 # 预言机（错误检测）
│   │   └── power_schedule.py         # 能量调度算法（baseline）
│   │
│   ├── fsms/                         # FSM图文件
│   │   ├── open5gs.dot               # Open5GS完整FSM
│   │   └── open5gs_sm.dot            # Open5GS会话管理FSM
│   │
│   ├── scripts/                      # 辅助脚本
│   │   └── init_db.py                # 数据库初始化脚本
│   │
│   ├── logs/                         # 日志文件目录
│   │   ├── core.log
│   │   ├── gnb.log
│   │   └── ue*.log
│   │
│   ├── UERANSIM_CoreTesting/         # UERANSIM（gNB和UE模拟器）
│   │   ├── build/                    # 编译后的可执行文件
│   │   ├── config/                   # 配置文件
│   │   └── src/                      # 源代码
│   │
│   ├── sample.yaml                   # 配置文件示例
│   ├── Dockerfile                    # Docker镜像构建文件
│   ├── requirements.txt              # Python依赖
│   ├── run_rl_200_iterations.sh      # RL实验运行脚本
│   │
│   ├── savedFSM_rl.json              # RL模式保存的FSM状态
│   ├── savedFSM_sm_rl.json           # RL模式保存的SM FSM状态
│   ├── rl_model_real.pth             # 训练好的RL模型
│   ├── rl_stats_real.json            # RL统计数据
│   └── rl_real_experiment.log        # RL实验日志
│
├── Corelearner/                      # 🧠 状态机学习器
│   ├── Corelearner.jar               # 主程序JAR文件
│   ├── core.properties               # 配置文件
│   ├── automatalib/                  # Automata库
│   ├── learnlib/                     # LearnLib库
│   ├── mylearner/                    # 自定义学习器
│   ├── scripts/                      # 辅助脚本
│   │   ├── start_core.sh             # 启动Open5GS
│   │   ├── kill_core.sh              # 停止Open5GS
│   │   ├── kill_gnb.sh               # 停止gNB
│   │   └── kill_ue.sh                # 停止UE
│   └── CEStore/                      # 反例存储目录
│
├── open5gs/                          # 📡 Open5GS 5G核心网
│   ├── build/                        # 编译输出
│   ├── configs/                      # 配置文件
│   ├── src/                          # 源代码
│   └── webui/                        # Web管理界面
│
├── UERANSIM_CoreTesting/             # 📱 UE和gNB模拟器（顶层副本）
│   ├── build/                        # 编译后的可执行文件
│   ├── config/                       # 配置文件
│   └── src/                          # 源代码
│
└── Other_fuzzers/                    # 🔬 其他模糊测试工具（用于对比）
    ├── eval_AFLNet/                  # AFLNet评估
    ├── eval_BooFuzz/                 # BooFuzz评估
    └── eval_Fuzzowski/               # Fuzzowski评估
```

---

## 核心组件说明

### 1. CoreFuzzer（模糊测试器）

**主要文件：**
- `core_fuzzer.py`: 主程序，集成了RL调度器，负责模糊测试的主循环
- `rl_scheduler.py`: DQN实现，负责状态选择和模型训练

**关键特性：**
- 支持RL和PowerSchedule两种调度模式（通过`USE_RL`标志切换）
- 在线学习：边模糊测试边训练模型
- 多维度奖励函数：考虑崩溃、协议违规、新状态、错误等
- 经验回放和目标网络：提高训练稳定性

### 2. Corelearner（状态机学习器）

**功能：**
- 使用TTT和WPMethod算法学习5G NAS协议的有限状态机
- 生成`.dot`格式的FSM图文件
- 为模糊测试提供状态空间

### 3. Open5GS（被测系统）

**说明：**
- 开源5G核心网实现
- 作为模糊测试的目标系统
- 需要预先编译和配置

### 4. UERANSIM（模拟器）

**功能：**
- 模拟5G gNB（基站）和UE（用户设备）
- 与Open5GS通信，生成NAS消息
- 支持模糊测试器的消息注入

---

## 工作流程

### 阶段1：状态机学习
```bash
cd Corelearner
java -jar Corelearner.jar core.properties
```
- 输出：`open5gs.dot`和`open5gs_sm.dot`

### 阶段2：模糊测试（RL模式）
```bash
cd CoreFuzzer
# Docker环境
docker run --rm -v $(pwd):/corefuzzer --privileged -it corefuzzer:sm bash
./run_rl_200_iterations.sh

# 或直接运行
python3 core_fuzzer.py sample.yaml
```

### 主循环逻辑：
1. **状态选择**：RL调度器基于当前全局特征选择状态
2. **消息生成**：从选定状态生成变异的NAS消息
3. **消息发送**：通过UERANSIM发送到Open5GS
4. **响应观测**：记录系统响应和异常
5. **奖励计算**：根据多维度指标计算奖励
6. **经验存储**：存入经验回放缓冲区
7. **模型训练**：当缓冲区足够大时，进行批量训练
8. **重复**：继续下一次迭代

---

## 关键配置

### RL参数（rl_scheduler.py）
```python
self.gamma = 0.99           # 折扣因子
self.epsilon = 1.0          # 初始探索率
self.epsilon_min = 0.01     # 最小探索率
self.epsilon_decay = 0.995  # 探索率衰减
self.batch_size = 32        # 批量大小
self.target_update_freq = 100  # 目标网络更新频率
```

### 奖励权重
```python
crash: +1000
protocol_violation: +500
new_state: +200
interesting_msg: +20
error: +10
over_visit_penalty: -0.1 per excess visit
```

---

## 实验结果

训练好的模型和数据位于：
- 模型：`CoreFuzzer/rl_model_real.pth`
- 统计：`CoreFuzzer/rl_stats_real.json`
- 日志：`CoreFuzzer/rl_real_experiment.log`
- FSM：`CoreFuzzer/savedFSM_rl.json`

详细分析请参考：`docs/EXPERIMENT_ANALYSIS.md`

---

## 快速开始

### 1. 环境准备
```bash
# 安装Python依赖
cd CoreFuzzer
pip install -r requirements.txt

# 编译Open5GS
cd ../open5gs
meson build --prefix=`pwd`/install
ninja -C build
```

### 2. 启动Open5GS
```bash
cd Corelearner/scripts
./start_core.sh
```

### 3. 运行模糊测试
```bash
cd CoreFuzzer
python3 core_fuzzer.py sample.yaml
```

更多详细信息请参考：`docs/DETAILED_EXECUTION_GUIDE.md`

---

## 文档导航

| 文档 | 用途 |
|------|------|
| `docs/QUICK_REFERENCE.md` | 快速查阅命令和参数 |
| `docs/RL_COREFUZZER_README.md` | RL增强的CoreFuzzer概述 |
| `docs/ALGORITHM_AND_WORKFLOW_GUIDE.md` | 算法原理和详细流程 |
| `docs/ONLINE_LEARNING_EXPLANATION.md` | 在线学习机制详解 |
| `docs/WHY_REINFORCEMENT_LEARNING.md` | 使用RL的优势和对比 |
| `docs/DETAILED_EXECUTION_GUIDE.md` | 完整的执行步骤 |
| `docs/EXPERIMENT_ANALYSIS.md` | 实验结果和问题分析 |
| `docs/PROJECT_FINAL_REPORT.md` | 项目总结报告 |

---

## 技术栈

- **编程语言**: Python 3.10+, Java 11+, C/C++
- **深度学习**: PyTorch
- **数据库**: MongoDB
- **容器化**: Docker
- **5G核心网**: Open5GS
- **UE/gNB模拟**: UERANSIM
- **状态机学习**: LearnLib + AutomataLib
- **模糊测试**: AFLNet (根据记忆，本项目使用AFLNet)

---

## 贡献者

本项目为5G核心网安全研究项目，旨在提高模糊测试效率和漏洞发现能力。

---

## 许可证

请参考 LICENSE 文件

---

## 相关链接

- **Open5GS**: https://open5gs.org/
- **UERANSIM**: https://github.com/aligungr/UERANSIM
- **LearnLib**: https://learnlib.de/
- **AFLNet**: https://github.com/aflnet/aflnet

---

*最后更新：2025年10月*


