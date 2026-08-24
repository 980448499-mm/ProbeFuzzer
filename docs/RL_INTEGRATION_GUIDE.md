# RL-ProbeFuzzer 集成指南

## 📋 改进概述

### 核心改进
将原来的**PowerSchedule**替换为**RLScheduler**，使用深度强化学习（DQN）学习最优的状态选择策略。

---

## 🔧 集成步骤

### 第1步：修改core_fuzzer.py的导入

```python
# 原来的导入
from objects.power_schedule import PowerSchedule

# 新增导入
from rl_scheduler import RLScheduler
import numpy as np
```

### 第2步：修改主函数初始化部分

```python
# 原来的代码（第228行）
schedule = PowerSchedule()

# 替换为
rl_scheduler = RLScheduler(num_states=len(fsm.states))

# 如果有预训练模型，加载它
if os.path.exists('./rl_model.pth'):
    rl_scheduler.load_model('./rl_model.pth')
    print("已加载预训练RL模型")
```

### 第3步：修改状态选择逻辑

```python
# 原来的代码（第269-270行）
schedule.adjustEnergy(fsm.states)
curr_state = schedule.choose(fsm.states)

# 替换为
# 获取当前全局特征
current_features = rl_scheduler.extract_global_features(fsm.states)

# 使用RL选择状态  
curr_state, action = rl_scheduler.choose_state_rl(fsm.states)
print(f"RL选择状态: {curr_state.name} (epsilon={rl_scheduler.epsilon:.3f})")
```

### 第4步：添加奖励计算和训练

在fuzzing循环的末尾（第477行之前）添加：

```python
# 计算测试结果
test_result = {
    'crashed': if_crash or if_crash_sm,
    'protocol_violation': violation,
    'new_state': resp_json.get("ret_type") != "" and not fsm.search_new_transition(...),
    'coverage_increase': 0,  # TODO: 实现覆盖率计算
    'state_visit_count': curr_state.count,
    'interesting': is_interesting,
    'error_triggered': if_error
}

# 计算奖励
reward = rl_scheduler.calculate_reward(test_result)

# 获取下一状态特征
next_features = rl_scheduler.extract_global_features(fsm.states)

# 存储经验
done = if_crash or if_crash_sm or violation
rl_scheduler.store_transition(current_features, action, reward, next_features, done)

# 训练网络
if len(rl_scheduler.memory) >= rl_scheduler.batch_size:
    loss = rl_scheduler.train()
    if loss and rl_scheduler.steps % 100 == 0:
        print(f"RL训练 - Loss: {loss:.4f}, Epsilon: {rl_scheduler.epsilon:.4f}")

# 定期保存模型
if rl_scheduler.steps % 500 == 0:
    rl_scheduler.save_model(f'./checkpoints/rl_model_step_{rl_scheduler.steps}.pth')
```

### 第5步：修改退出处理

```python
# 原来的exit_handler
def exit_handler(fsm: FSM, fsm_sm: FSM):
    ...

# 修改为
def exit_handler(fsm: FSM, fsm_sm: FSM, rl_scheduler: RLScheduler):
    ...
    # 保存RL模型
    rl_scheduler.save_model('./rl_model.pth')
    
# 注册时也要修改
atexit.register(exit_handler, fsm, fsm_sm, rl_scheduler)
```

---

## 📊 完整的修改对比

### core_fuzzer.py 关键修改

```diff
# Line 7: 添加导入
+ from rl_scheduler import RLScheduler
+ import numpy as np

# Line 228: 替换调度器
- schedule = PowerSchedule()
+ rl_scheduler = RLScheduler(num_states=len(fsm.states))
+ if os.path.exists('./rl_model.pth'):
+     rl_scheduler.load_model('./rl_model.pth')

# Line 269-270: 替换状态选择
- schedule.adjustEnergy(fsm.states)
- curr_state = schedule.choose(fsm.states)
+ current_features = rl_scheduler.extract_global_features(fsm.states)
+ curr_state, action = rl_scheduler.choose_state_rl(fsm.states)

# Line 477前: 添加RL训练逻辑
+ test_result = {...}
+ reward = rl_scheduler.calculate_reward(test_result)
+ next_features = rl_scheduler.extract_global_features(fsm.states)
+ rl_scheduler.store_transition(current_features, action, reward, next_features, done)
+ if len(rl_scheduler.memory) >= rl_scheduler.batch_size:
+     loss = rl_scheduler.train()

# Line 12, 250: 修改exit_handler
- def exit_handler(fsm: FSM, fsm_sm: FSM):
+ def exit_handler(fsm: FSM, fsm_sm: FSM, rl_scheduler: RLScheduler):
+     rl_scheduler.save_model('./rl_model.pth')

- atexit.register(exit_handler, fsm, fsm_sm)
+ atexit.register(exit_handler, fsm, fsm_sm, rl_scheduler)
```

---

## 🚀 使用方法

### 创建检查点目录

```bash
mkdir -p checkpoints
```

### 运行RL版本

```bash
# 首次运行（从头训练）
python3 core_fuzzer_rl.py

# 继续训练（加载模型）
python3 core_fuzzer_rl.py  # 自动加载rl_model.pth
```

### 查看训练进度

```bash
# 实时查看
tail -f statelearner.log | grep -E "(RL选择|奖励|训练)"

# 查看统计
cat rl_stats.json
```

---

## 📊 对比实验设计

### 实验设置

1. **基线**: 原版ProbeFuzzer (PowerSchedule)
2. **改进版**: RL-ProbeFuzzer (RLScheduler)

### 评估指标

| 指标 | 说明 |
|-----|-----|
| 漏洞发现数量 | 发现的崩溃、违规数 |
| 漏洞发现时间 | 首次发现漏洞的迭代数 |
| 状态覆盖率 | 覆盖的状态比例 |
| 状态访问平衡度 | max访问/min访问 |
| 新状态发现数 | 动态发现的新状态数 |
| 有趣消息数量 | 触发新行为的消息数 |

### 实验流程

```bash
# 1. 运行原版（1000次迭代）
python3 core_fuzzer.py
# 记录结果 -> baseline_results.json

# 2. 运行RL版本（1000次迭代）
python3 core_fuzzer_rl.py  
# 记录结果 -> rl_results.json

# 3. 对比分析
python3 compare_results.py baseline_results.json rl_results.json
```

---

## 🎓 论文贡献点

### 1. 技术创新

**标题**: "RL-Fuzz: Reinforcement Learning Guided Stateful Fuzzing for 5G Core Networks"

**核心贡献**:
- 首次将DQN应用于状态机引导的协议模糊测试
- 自适应的状态选择策略学习
- 基于多维度奖励的优化目标

### 2. 实验贡献

**对比实验**:
- 原版 vs RL版本
- 漏洞发现效率提升X%
- 状态覆盖率提升Y%
- 访问平衡度改善Z倍

### 3. 系统贡献

**开源工具**:
- RL-ProbeFuzzer框架
- 预训练模型
- 实验数据集

---

## 📈 预期结果

### 性能提升预期

| 指标 | 基线 | RL版本 | 提升 |
|-----|------|--------|-----|
| 漏洞发现数 | X | X+Y | +Y个 |
| 状态覆盖率 | 94% | 98%+ | +4% |
| 访问平衡度 | 6.2倍 | 2倍 | 改善3倍 |
| 新状态发现 | Z | Z+W | +W个 |

### 学习曲线

预期RL agent会经历：
1. **探索阶段** (0-200迭代): epsilon高，随机探索
2. **学习阶段** (200-500迭代): 逐渐学习有效策略
3. **利用阶段** (500+迭代): epsilon低，利用学到的策略

---

## 🔬 进一步改进

### 可选的增强

1. **优先经验回放** (Prioritized Experience Replay)
2. **Double DQN** (减少Q值过估计)
3. **Dueling DQN** (分离状态值和优势函数)
4. **Multi-step Learning** (n-step returns)
5. **PPO算法** (更稳定的策略梯度方法)

---

## ✅ 当前状态

- ✅ RL调度器已实现
- ✅ DQN网络已创建
- ✅ 奖励函数已设计
- ✅ PyTorch环境已配置
- ⏭️ 需要完整集成到core_fuzzer.py
- ⏭️ 需要运行对比实验

---

**下一步**: 创建完整集成版本的core_fuzzer.py


