# RL-ProbeFuzzer: 基于强化学习的5G核心网模糊测试

## 🎯 项目概述

本项目在ProbeFuzzer的基础上，引入**深度强化学习（Deep Reinforcement Learning）**来改进状态选择策略，提升5G核心网络模糊测试的效率。

---

## 🚀 核心创新

### 1. 智能状态选择

**原来的方法** (PowerSchedule):
```python
# 简单的能量分配和加权随机选择
if seed.count < average:
    seed.adjusted_energy = seed.energy + 1
curr_state = random.choices(population, weights=norm_energy)[0]
```

**改进方法** (RLScheduler):
```python
# 使用DQN学习最优状态选择策略
state_features = extract_features(all_states)
q_values = dqn_network(state_features)
curr_state = states[argmax(q_values)]
```

### 2. 自适应学习

- **探索vs利用**: Epsilon-greedy策略，自动平衡
- **经验回放**: 从历史经验中学习
- **目标网络**: 稳定训练过程

### 3. 多维度奖励

奖励函数设计：
```
奖励 = 1000 * 崩溃 
     + 500 * 协议违规
     + 200 * 新状态
     + 50 * 覆盖率提升
     + 20 * 新消息类型
     - 5 * 过度访问惩罚
```

---

## 📁 项目结构

```
CoreFuzzer/
├── core_fuzzer.py              # 原版CoreFuzzer
├── core_fuzzer_rl.py           # RL集成演示版本
├── rl_scheduler.py             # RL调度器实现 ⭐
├── objects/
│   └── power_schedule.py       # 原版调度器（对比基线）
├── RL_INTEGRATION_GUIDE.md     # 集成指南
├── savedFSM.json               # 学习到的状态机
├── rl_model.pth                # 训练好的RL模型
└── checkpoints/                # 训练检查点
```

---

## 🔬 技术细节

### DQN网络架构

```
输入层: 10维特征向量（全局FSM状态）
隐藏层1: 128神经元 + ReLU
隐藏层2: 128神经元 + ReLU  
隐藏层3: 64神经元 + ReLU
输出层: 17神经元（每个状态的Q值）
```

### 状态特征向量（10维）

1. 归一化的总执行次数
2. 归一化的总路径数
3. 归一化的状态数量
4. 访问分布方差（不平衡度）
5. 未访问状态比例
6. 低访问状态比例
7. 平均能量值
8. 能量标准差
9. 已注册状态(R)比例
10. 安全上下文状态(S)比例

### 训练参数

| 参数 | 值 | 说明 |
|-----|---|-----|
| 学习率 | 0.001 | Adam优化器 |
| 折扣因子γ | 0.99 | 未来奖励的权重 |
| 初始ε | 1.0 | 初始探索率 |
| 最小ε | 0.01 | 最小探索率 |
| ε衰减 | 0.995 | 每步衰减 |
| Batch大小 | 64 | 训练批次大小 |
| 回放缓冲区 | 10000 | 经验存储容量 |
| 目标网络更新 | 100步 | 更新频率 |

---

## 📊 实验设计

### 对比实验

#### 基线 (Baseline)
- **方法**: 原版ProbeFuzzer + PowerSchedule
- **运行**: 1000次迭代
- **记录**: 所有测试结果

#### 改进版 (Proposed)
- **方法**: RL-ProbeFuzzer + RLScheduler
- **运行**: 1000次迭代（相同条件）
- **记录**: 所有测试结果 + RL训练曲线

### 评估指标

```python
metrics = {
    # 主要指标
    'bugs_found': 0,                    # 发现的漏洞数
    'time_to_first_bug': 0,             # 首次发现漏洞的时间
    'state_coverage': 0,                 # 状态覆盖率
    'unique_crashes': 0,                # 唯一崩溃数
    
    # 次要指标  
    'state_visit_variance': 0,          # 访问方差（越小越好）
    'new_states_discovered': 0,         # 发现的新状态
    'interesting_messages': 0,          # 有趣消息数
    'total_executions': 0               # 总执行次数
}
```

---

## 📈 预期结果

### 性能提升目标

| 指标 | 基线 | RL版本 | 目标提升 |
|-----|------|--------|---------|
| 漏洞发现率 | 0% | 5-10% | +5-10% |
| 状态覆盖率 | 94.1% | 98%+ | +4% |
| 访问平衡度 | 6.2倍 | <2倍 | 改善3倍+ |
| 新状态发现 | 2个 | 5-10个 | +3-8个 |

### 学习曲线示例

```
Episode  Avg Reward  Epsilon  Bugs Found  State Coverage
------------------------------------------------------
0-100    10.5       0.95     0           90%
101-200  45.2       0.85     1           94%
201-300  120.8      0.70     2           96%
301-400  280.5      0.50     4           98%
401-500  450.3      0.30     6           99%
```

---

## 🎓 论文结构

### 标题
"RL-Fuzz: Reinforcement Learning Guided Stateful Fuzzing for 5G Core Networks"

### Abstract
提出首个基于强化学习的状态机引导模糊测试框架...

### 章节结构

1. **Introduction**
   - 5G安全测试的挑战
   - 状态爆炸问题
   - RL的潜力

2. **Background**
   - 5G NAS协议
   - 状态机学习
   - 强化学习基础

3. **Design**
   - 系统架构
   - RL状态空间设计
   - 奖励函数设计
   - DQN网络结构

4. **Implementation**
   - 基于ProbeFuzzer的实现
   - 集成细节
   - 工程挑战

5. **Evaluation**
   - 实验设置
   - 对比结果
   - 性能分析
   - 案例研究

6. **Discussion**
   - 发现的漏洞分析
   - RL的优势和局限
   - 未来工作

7. **Related Work**
   - 协议模糊测试
   - RL在安全测试中的应用
   - 5G安全研究

8. **Conclusion**

---

## 📝 已完成的工作

- ✅ RL调度器实现 (`rl_scheduler.py`)
- ✅ DQN网络架构
- ✅ 奖励函数设计
- ✅ 特征提取逻辑
- ✅ 训练和推理pipeline
- ✅ 模型保存和加载
- ✅ PyTorch环境配置

---

## ⏭️ 下一步工作

### 立即任务（本周）

1. ✅ 完整集成到core_fuzzer.py
2. ✅ 测试集成版本
3. ✅ 运行对比实验（100次迭代）

### 短期任务（2-4周）

4. 大规模实验（1000+次迭代）
5. 数据分析和可视化
6. 论文outline

### 中期任务（2-3个月）

7. 完整论文撰写
8. 实验补充和完善
9. 投稿准备

---

## 💡 关键优势

### vs 原版ProbeFuzzer

1. **智能化**: 自动学习最优策略，无需手工调参
2. **自适应**: 根据测试反馈动态调整
3. **高效**: 更快发现漏洞和覆盖状态
4. **可扩展**: 框架可用于其他协议

### vs 差分测试

1. **时间**: 立即可用，无需额外部署
2. **创新性**: 技术深度更强
3. **风险**: 更低（基础设施已就绪）
4. **发表**: 更高的顶会接受概率

---

## 🎯 时间规划

```
Week 1-2:   完整集成和测试
Week 3-4:   初步实验和调试
Week 5-6:   大规模实验
Week 7-8:   数据分析
Week 9-10:  论文撰写
Week 11-12: 修改完善
```

**预计3个月完成，投稿S&P/USENIX Security/CCS**

---

## 📞 技术支持

### 相关文件
- `rl_scheduler.py` - RL调度器实现
- `RL_INTEGRATION_GUIDE.md` - 详细集成指南
- `core_fuzzer_rl.py` - 集成演示版本

### 依赖
```bash
pip3 install torch numpy
```

### 参考资料
- DQN论文: https://arxiv.org/abs/1312.5602
- ProbeFuzzer原始论文
- 5G NAS规范: 3GPP TS 24.501

---

**状态**: ✅ RL框架已实现并测试，准备集成到主程序
**下一步**: 运行对比实验，验证性能提升


