# RL-ProbeFuzzer 项目文档索引

## 📚 快速导航

### 🔥 推荐阅读顺序

1. **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - 3分钟快速了解项目
2. **[ALGORITHM_AND_WORKFLOW_GUIDE.md](ALGORITHM_AND_WORKFLOW_GUIDE.md)** - 30分钟深入理解算法
3. **[PROJECT_FINAL_REPORT.md](PROJECT_FINAL_REPORT.md)** - 项目完整报告

---

## 📖 文档分类

### 核心文档（必读）

#### 1. QUICK_REFERENCE.md 
**快速参考指南** - 2.8KB
- 🎯 3个核心算法概述
- 🔄 6步运行流程
- 📊 关键实验数据
- 💻 核心代码片段
- 🎓 论文要点
- **适合**: 快速了解项目全貌

#### 2. ALGORITHM_AND_WORKFLOW_GUIDE.md  
**算法和流程详解** - 36KB
- 🏗️ 系统整体架构
- 🔬 算法详细流程（TTT, DQN, 变异）
- 🔄 完整运行流程
- 🔑 关键算法实现
- 📊 数据流图
- 💡 单次迭代示例
- **适合**: 深入理解技术细节

#### 3. PROJECT_FINAL_REPORT.md  
**项目最终报告** - 7.2KB
- ✅ 完成工作清单
- 🏆 核心成果统计
- 📁 交付物清单
- 🎓 论文准备状态
- 📝 论文撰写计划
- **适合**: 整体把握项目状态

---

### 技术文档

#### 4. RL_COREFUZZER_README.md
**RL技术方案** - 6.9KB
- RL框架设计
- DQN网络架构
- 奖励函数设计
- 特征工程
- **适合**: 了解RL方案设计思路

#### 5. RL_INTEGRATION_GUIDE.md
**RL集成指南**
- 代码集成步骤
- 关键修改点
- 配置参数
- **适合**: 理解代码如何集成RL

#### 6. EXPERIMENT_ANALYSIS.md
**实验结果分析**
- 性能对比数据
- 统计分析
- 可视化图表
- **适合**: 了解实验效果

---

### 规划文档

#### 7. PROJECT_COMPLETE_SUMMARY.md
**项目完成总结** - 13KB
- 详细工作记录
- 技术决策过程
- 问题和解决方案
- **适合**: 回顾项目历程

#### 8. FINAL_SUMMARY.md
**最终总结** - 6.6KB
- 研究问题定义
- 方法论
- 贡献总结
- **适合**: 论文素材准备

---

### 参考文档（已废弃）

#### 9. DIFFERENTIAL_TESTING_PLAN.md
**差分测试计划** - 9.7KB
- Free5GC集成方案
- 差分测试设计
- **状态**: 已搁置，作为参考

#### 10. DIFFERENTIAL_TESTING_STATUS.md
**差分测试状态** - 3.5KB
- Free5GC部署尝试
- 遇到的问题
- **状态**: 已放弃

---

## 🖼️ 可视化图表

### RL_ProbeFuzzer_Workflow.png
**流程可视化图** - 209KB
- 左图：算法流程（TTT → DQN → 变异 → 输出）
- 右图：运行流程（7步详细流程）
- **用途**: 论文插图、演示PPT

### DQN_Network_Structure.png  
**DQN网络结构图** - 243KB
- 输入特征（10维）
- 网络层次（4层）
- Q值输出（17维）
- 训练过程
- 超参数和性能
- **用途**: 论文网络架构图

### experiment_comparison.png
**实验对比图** - 390KB（在CoreFuzzer/目录）
- 新状态发现对比
- 有趣消息对比
- Loss收敛曲线
- **用途**: 论文实验结果图

---

## 💻 代码文件

### 核心实现

```
CoreFuzzer/
├── rl_scheduler.py (454行)           # RL调度器核心
├── core_fuzzer.py (579行)            # RL集成版本
├── core_fuzzer.py.bak                # 原版备份
├── experiment_rl_vs_baseline.py      # 对比实验
└── run_rl_experiment_in_docker.sh    # Docker运行脚本
```

### 关键代码位置

| 功能 | 文件 | 行号 |
|-----|------|------|
| DQN网络 | rl_scheduler.py | 20-32 |
| 特征提取 | rl_scheduler.py | 145-176 |
| 奖励计算 | rl_scheduler.py | 178-206 |
| DQN训练 | rl_scheduler.py | 208-237 |
| RL状态选择 | core_fuzzer.py | 315-321 |
| RL训练逻辑 | core_fuzzer.py | 538-562 |
| NAS变异 | UERANSIM_CoreTesting/src/lib/nas/nas_mutator.cpp | 全文 |

---

## 📊 实验数据

### 模拟实验结果

```
CoreFuzzer/
├── experiment_results.json          # 实验数据
├── experiment_comparison.png        # 对比图表
├── experiment_output.log            # 详细日志
└── rl_model_experiment.pth          # 训练模型
```

### 真实实验结果

```
CoreFuzzer/
├── savedFSM_rl.json                 # RL生成的状态机
├── rl_model_real.pth                # 真实环境训练的模型
├── rl_real_experiment.log           # 真实实验日志
└── rl_stats.json                    # RL统计信息
```

---

## 🎓 论文相关

### 论文信息
- **标题**: "RL-Fuzz: Reinforcement Learning Guided Stateful Fuzzing for 5G Core Networks"
- **目标**: IEEE S&P / USENIX Security 2026
- **时间**: 2-2.5个月
- **成功率**: 85%+

### 论文素材位置

| 章节 | 素材来源 |
|-----|---------|
| Abstract | QUICK_REFERENCE.md |
| Introduction | PROJECT_FINAL_REPORT.md |
| Background | ALGORITHM_AND_WORKFLOW_GUIDE.md (阶段1) |
| Design | ALGORITHM_AND_WORKFLOW_GUIDE.md (阶段2) + RL_COREFUZZER_README.md |
| Implementation | RL_INTEGRATION_GUIDE.md + core_fuzzer.py |
| Evaluation | EXPERIMENT_ANALYSIS.md + experiment_results.json |
| Figures | RL_ProbeFuzzer_Workflow.png + DQN_Network_Structure.png + experiment_comparison.png |

---

## 🔍 按需查找

### 我想了解...

#### "项目做了什么？"
→ **QUICK_REFERENCE.md** 或 **PROJECT_FINAL_REPORT.md**

#### "算法怎么工作的？"
→ **ALGORITHM_AND_WORKFLOW_GUIDE.md**

#### "代码怎么实现的？"
→ **RL_INTEGRATION_GUIDE.md** + 代码文件

#### "实验效果如何？"
→ **EXPERIMENT_ANALYSIS.md** + experiment_comparison.png

#### "如何运行？"
→ **RL_COREFUZZER_README.md** + run_rl_experiment_in_docker.sh

#### "有什么创新？"
→ **FINAL_SUMMARY.md** + ALGORITHM_AND_WORKFLOW_GUIDE.md (RL部分)

#### "论文怎么写？"
→ **PROJECT_FINAL_REPORT.md** (论文撰写计划)

---

## 📈 项目统计

### 代码统计
- **核心代码**: 1800+行
- **核心文件**: 3个（rl_scheduler.py, core_fuzzer.py, experiment_rl_vs_baseline.py）
- **变异算法**: 156行C++代码

### 文档统计
- **文档总数**: 10个Markdown文件
- **文档总字数**: ~80,000字
- **可视化图表**: 3张PNG图

### 实验统计
- **状态机学习**: 17个状态，191条路径
- **模拟实验**: 500次迭代
- **性能提升**: 新状态+50%，有趣消息+14.3%
- **模型大小**: 448KB

---

## 🎯 快速命令

### 查看文档
```bash
# 快速参考
cat QUICK_REFERENCE.md

# 详细算法
less ALGORITHM_AND_WORKFLOW_GUIDE.md

# 项目报告
cat PROJECT_FINAL_REPORT.md
```

### 运行实验
```bash
# 模拟实验
cd CoreFuzzer
python3 experiment_rl_vs_baseline.py

# 真实实验（Docker）
./run_rl_experiment_in_docker.sh
```

### 查看图表
```bash
# 流程图
xdg-open RL_ProbeFuzzer_Workflow.png

# 网络结构
xdg-open DQN_Network_Structure.png

# 实验对比
xdg-open CoreFuzzer/experiment_comparison.png
```

---

## 📞 联系信息

**项目**: RL-ProbeFuzzer  
**完成日期**: 2025-10-10  
**状态**: ✅ 完成，准备论文撰写

---

**最后更新**: 2025-10-10 11:15


