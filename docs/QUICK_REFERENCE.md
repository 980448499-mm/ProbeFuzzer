# RL-ProbeFuzzer 快速参考

## 🎯 核心算法（3个）

### 1. TTT状态机学习
```
Corelearner (Java) → 学习5G协议状态机
算法: Tree-based Testing + WPMethod
输出: 17个状态，191条路径
```

### 2. DQN状态选择  
```
RL Scheduler (Python) → 智能选择测试状态
算法: Deep Q-Network
性能: 新状态发现+50%
```

### 3. NAS消息变异
```
UERANSIM (C++) → 生成变异测试消息
算法: 字节级+结构级变异
位置: nas_mutator.cpp
```

---

## 🔄 运行流程（6步）

```
1. 加载状态机 → savedFSM.json (17个状态)
2. 初始化RL → DQN网络 (10→128→128→64→17)
3. 选择状态 → DQN(features) → argmax(Q值)
4. 执行测试 → 发送NAS消息到Open5GS
5. 收集反馈 → 崩溃/违规/新状态/错误
6. RL训练 → 存储经验 → 训练网络 → 更新策略
```

---

## 📊 关键数据

### 状态机学习结果
- 状态数: 17个
- 路径数: 191条
- 执行次数: 1480次
- 测试消息: 1561次

### RL训练结果
- 新状态: +50% (6 vs 4)
- 有趣消息: +14.3% (376 vs 329)
- Loss收敛: 686 → 100
- 模型大小: 448KB

---

## 💻 核心代码

### RL状态选择
```python
# core_fuzzer.py:315-321
features = rl_scheduler.extract_global_features(fsm.states)
action = rl_scheduler.select_action(features, fsm.states)
curr_state = fsm.states[action]
```

### RL训练
```python
# core_fuzzer.py:538-562
reward = rl_scheduler.calculate_reward(test_result)
rl_scheduler.store_transition(features, action, reward, next_features, done)
loss = rl_scheduler.train()
```

### DQN网络
```python
# rl_scheduler.py:20-32
class DQNetwork(nn.Module):
    fc1: Linear(10, 128)
    fc2: Linear(128, 128)
    fc3: Linear(128, 64)
    fc4: Linear(64, 17)
```

---

## 🎓 论文要点

**标题**: "RL-Fuzz: Reinforcement Learning Guided Stateful Fuzzing for 5G Core Networks"

**核心贡献**:
1. 首次DQN用于状态机模糊测试
2. 新状态发现+50%
3. 完整开源实现

**目标**: S&P/USENIX Security 2026
**时间**: 2-2.5个月
**成功率**: 85%

---

## 📁 重要文件

```
CoreFuzzer/
├── rl_scheduler.py              # RL核心
├── core_fuzzer.py               # RL集成版
├── experiment_rl_vs_baseline.py # 实验脚本
├── experiment_results.json      # 结果数据
└── experiment_comparison.png    # 对比图表

文档/
├── ALGORITHM_AND_WORKFLOW_GUIDE.md  # 详细算法流程
├── RL_COREFUZZER_README.md          # 技术方案
├── PROJECT_FINAL_REPORT.md          # 项目报告
└── QUICK_REFERENCE.md               # 本文件
```

---

**快速查找**: 
- 算法详解 → ALGORITHM_AND_WORKFLOW_GUIDE.md
- 代码集成 → RL_INTEGRATION_GUIDE.md
- 实验结果 → EXPERIMENT_ANALYSIS.md
- 项目总结 → PROJECT_FINAL_REPORT.md
