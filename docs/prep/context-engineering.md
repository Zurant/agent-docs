# Context 工程 (Context Engineering)

Context 工程是保障大模型“不胡说八道（幻觉）”的基石。它的核心解决思路是：如何在有限的 Token 上下文窗口内，高效、精准地输送外部知识和业务状态。

## 1. 记忆机制 (Memory Management)
Agent 与传统 LLM API 调用的核心区别在于状态保持。
- **短期记忆 (Short-term Memory)**: 管理当前会话的上下文。
  - **滑动窗口 (Sliding Window)**: 只保留最近 N 轮对话，防止 Token 爆炸。
  - **消息摘要 (Message Summarization)**: 当对话达到一定长度时，触发后台大模型对前文进行压缩总结，保留核心脉络。
- **长期记忆 (Long-term Memory)**: 将用户的核心特征、历史偏好持久化。
  - 通常结合向量数据库 (Vector DB) 或知识图谱，在系统启动或多轮交互中，动态抽取相关“用户画像”注入到 Prompt 中。

## 2. 检索增强生成 (RAG - Retrieval-Augmented Generation)
在工业界，RAG 是 Context 工程的重中之重，包含完整的搜索推荐架构思维。

### 检索前 (Pre-retrieval)
- **Query Rewrite (查询重写)**: 用户的原始问题往往口语化且残缺，通过小模型将其重写为标准化、利于搜索的检索词。
- **HyDE (假设性文档嵌入)**: 让模型先凭空“幻觉”生成一段答案，再拿这段答案去向量库里搜索真实文档（基于语义相似度匹配得更准）。
- **Query Routing (智能分发)**: 判断用户的问题应该查日志库、查代码库，还是查通识向量库。

### 检索中 (Retrieval)
- **多路召回**: 结合 Dense Retrieval (向量语义检索，如 Milvus) 和 Sparse Retrieval (稀疏关键词检索，如 BM25 Elasticsearch)，保障精确匹配与语义匹配的平衡。
- **Chunking (文档分块策略)**: 
  - 暴力切分 (Fixed-size)
  - 语义切分 (Semantic splitting)
  - 针对代码的 AST (抽象语法树) 切片，确保方法块的完整性，降低幻觉。

### 检索后 (Post-retrieval)
- **Reranking (重排)**: 召回回来的多路文档可能质量参差不齐，使用 Cross-Encoder 模型（如 bge-reranker）根据 Query 和 Doc 的相关性重新打分排序。
- **去重与合并**: 过滤掉高度重复的内容，提炼最核心的 Context 喂给最终的生成模型。

## 3. 长文本与 Token 级优化
- **KV Cache 原理**: 理解大模型底层的注意力机制缓存，如何在多轮对话中利用 KV Cache 加速推理 (TTFT)。
- **Token 预算与防抖限制**: 设计企业级的限流策略，例如相同报错栈的并发拦截，避免无效 Token 的海量浪费。
