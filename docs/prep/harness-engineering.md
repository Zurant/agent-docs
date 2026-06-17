# Harness 工程 (Harness & MLOps Engineering)

Harness 工程（测试台/评估与治理体系）关注的是 AI Agent 上线前后的质量保障、可观测性与迭代闭环。从“跑通 Demo”到“工业级系统上线”，Harness 是最重要的分水岭。

## 1. 测试与评估指标体系 (Evaluation)
大模型系统缺乏绝对标准的单元测试，必须依靠多维度的评估体系。
- **RAG 质量评估 (如 RAGAS 框架)**:
  - **Faithfulness (忠实度)**: 模型的回答是否完全基于检索到的 Context，有无捏造幻觉。
  - **Answer Relevance (答案相关性)**: 回答是否直接解决用户的 Query。
  - **Context Precision/Recall (上下文精准度/召回率)**: 评估向量库的检索链路是否优秀。
- **LLM-as-a-Judge**: 使用更高阶的模型（例如 GPT-4o 或 Claude-3.5-Sonnet）作为裁判，自动化评估本地模型或开源小模型的输出质量。

## 2. 可观测性与追踪 (Observability)
线上出了 Bug 不能“两眼一抹黑”，需要全链路监控。
- **Agent 链路追踪 (Tracing)**: 接入如 Langfuse, LangSmith 等工具，清晰记录 DAG (有向无环图) 状态机中每一步的输入输出、使用的 Tool 以及耗时。
- **核心业务指标**:
  - **TTFT (Time To First Token)**: 首字响应延迟，直接影响 C 端用户体验。
  - **TPS (Tokens Per Second)**: 吞吐量指标。
  - **Token 审计与计费**: 精准把控每个业务方或用户的 Token 开销成本。

## 3. 定制化增强与对齐 (Tuning & Alignment)
当 Prompt 工程到达天花板，需要对模型“动刀子”。
- **SFT (Supervised Fine-Tuning) / LoRA 微调**: 针对特定的输出格式要求（例如输出严格的 JSON 代码补全）、或注入领域黑话，采用低秩微调 (LoRA) 训练，降低推理 Token 消耗，提高稳定性。
- **RLHF (人类反馈强化学习) / DPO (直接偏好优化)**: 收集业务专家的“好/坏”打分数据，引导大模型的价值观和语气向符合企业文化的方向对齐。

## 4. 鲁棒性与边界测试 (Red Teaming)
- **红蓝对抗测试**: 使用自动化脚本甚至另一个专门攻击的大模型，疯狂抛出边界测试案例 (Corner Cases) 来攻击系统。
- **异常态兜底 (Fallback 机制)**:
  - 当大模型由于并发高不可用时，系统如何优雅降级（如切换回传统的搜索树或返回固定话术）。
  - API 调用的重试机制与超时挂起。
