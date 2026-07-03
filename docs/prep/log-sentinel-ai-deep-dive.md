# Log-Sentinel-AI 项目架构与核心技术深挖

本文档用于梳理 `log-sentinel-ai` 的项目架构与核心实现，重点覆盖诊断主链路、Milvus RAG、reranker、召回精度评估、LLM 工具调用、Qwen LoRA 垂类微调和工程化降级策略，可用于技术评审、面试讲解和优化参考。

---

## 1. 项目定位与整体链路

`log-sentinel-ai` 是一个面向 Java 微服务异常日志的智能诊断系统。它接收 Kafka 或 HTTP 上报的错误日志，经过限流、RAG 历史经验召回、大模型诊断、源码工具调用、知识沉淀和告警推送，最终形成可追溯的诊断报告。

核心链路如下：

```text
LogEvent(Kafka/HTTP)
  -> LogThrottler 本地 + Redis 两级限流
  -> StackTraceCompressor / LogFeatureExtractor 提取异常特征
  -> DiagnosisKnowledgeBase 从 Milvus 召回历史经验
  -> LogDiagnosisRouter 选择本地或云端大模型
  -> LogAnalyzerAgent 结合 RAG、日志和工具调用生成 DiagnosisReport
  -> DiagnosisKnowledgeBase.store 写回 Milvus
  -> MySQL 保存请求记录
  -> WeChatAlertNotifier 推送企微告警
```

主入口包括：

- HTTP：`POST /api/v1/log/diagnose`
- Kafka：消费 `sentinel-error-logs` topic
- Dashboard：提供统计、历史记录和知识详情接口
- 定时任务：`KnowledgeConsolidationJob` 每周生成稳定性报告

---

## 2. LLM 配置与模型路由

项目使用 LangChain4j 统一封装大模型能力。`AiConfig.java` 中配置了两个 `ChatModel`：

| 模型类型 | 配置前缀 | 默认配置 | 说明 |
| --- | --- | --- | --- |
| 云端模型 | `langchain4j.google.ai-gemini.*` | `deepseek-v4-flash` | 实际通过 OpenAI-compatible 代理访问，不是原生 Gemini SDK |
| 本地模型 | `langchain4j.open-ai.local.*` | `qwen3.5:9b` | 通过 Ollama/OpenAI-compatible 接口访问 |

主模型选择由：

```yaml
sentinel.ai.provider: ${AI_PROVIDER:cloud}
```

决定：

- `cloud`：使用 `deepseek-v4-flash`，作为默认诊断模型。
- `local`：使用本地 Ollama chat model。

代码中的配置前缀和变量名保留了 `google.ai-gemini`、`geminiBaseUrl`、`geminiModelName` 命名，但实际通过 OpenAI-compatible 代理访问 `deepseek-v4-flash`。

### 2.1 Qwen LoRA 垂类微调

项目针对本地 Qwen 指令模型做过一次日志诊断垂类 LoRA 微调。微调目标不是让模型记住所有历史故障，也不是替代 RAG、源码工具或结构化解析校验，而是解决长上下文日志诊断中更具体的工程问题：当 prompt 同时包含异常堆栈、RAG 历史案例、源码上下文和输出格式约束时，通用指令模型容易出现输出格式漂移，例如混入 Markdown 解释、遗漏必需字段、严重级别枚举不稳定、`traceId` 与输入不一致，或者为了满足格式说明牺牲根因分析内容。

因此这次微调的核心目标是提升模型的 schema following 和 SOP following 能力，让模型默认按项目内部诊断报告格式输出，而不是每次都依赖很长的 System Prompt 反复约束。

#### 2.1.1 为什么需要微调

在日志诊断场景中，输入通常不是短问答，而是多源上下文拼接后的长文本：

- 原始 Java 异常堆栈，可能包含多层 `Caused by`、框架栈和业务栈。
- RAG 召回的历史相似案例。
- GitLab 源码工具返回的方法级源码片段。
- 当前服务名、traceId、commitId、环境和诊断要求。

通用 Qwen 指令模型在短输入下可以较好遵循 JSON 输出，但在长上下文下更容易被异常堆栈、历史案例文本或源码注释干扰，典型问题包括：

1. 输出前后出现解释性自然语言，导致 JSON parser 解析失败。
2. `severityLevel` 输出为 `严重`、`P1`、`中等` 等非项目枚举。
3. `relatedFiles` 引用历史案例里的类名，而不是当前异常栈或源码中的类名。
4. `traceId` 使用历史案例 traceId，或被模型重新生成。
5. 修复建议过于模板化，没有贴合内部 SOP 中“根因、影响面、修复动作、验证方式”的表达习惯。

Prompt 工程可以缓解这些问题，但会带来两个副作用：一是 System Prompt 越写越长，推理 token 成本上升；二是格式约束越多，模型留给根因分析的注意力越少。LoRA 微调的价值在于把稳定输出格式和内部表达习惯内化为模型行为，使 prompt 可以更聚焦于当前故障事实。

#### 2.1.2 训练数据设计

训练数据来自脱敏后的排障样本，按 Alpaca JSONL 格式组织，每条样本包含：

- `instruction`：固定任务说明，要求模型扮演 Java 微服务日志诊断专家，并只输出合法 JSON。
- `input`：服务名、TraceID、异常堆栈、RAG 历史案例和源码上下文。
- `output`：人工整理或复核后的内部 SOP JSON 诊断报告。

样本结构示例：

```json
{
  "instruction": "You are a Java microservice log diagnosis expert. Based on the service name, trace ID, error stack, RAG historical cases, and source-code context, output only a valid JSON diagnosis report that follows the internal SOP schema.",
  "input": "ServiceName: vs-player\nTraceID: trace-train-0001\nErrorStack:\n...\nHistoricalCases:\n...\nSourceContext:\n...",
  "output": "{\"traceId\":\"trace-train-0001\",\"rootCause\":\"...\",\"severityLevel\":\"HIGH\",\"fixSuggestion\":\"...\",\"relatedFiles\":[\"com.vs.player.service.PlayerServiceImpl\"]}"
}
```

输出字段固定为：

| 字段 | 说明 |
| --- | --- |
| `traceId` | 必须与输入 TraceID 一致，防止历史案例 traceId 串入当前报告 |
| `rootCause` | 说明真实失败链路，不能只复述异常类型 |
| `severityLevel` | 只能取 `LOW`、`MEDIUM`、`HIGH`、`CRITICAL` |
| `fixSuggestion` | 给出可执行修复建议，包含参数校验、配置修复、代码修改或回滚建议 |
| `relatedFiles` | 只允许引用当前堆栈、源码上下文或服务模块中出现的类 |

脱敏时保留诊断必要信号，例如异常类型、类名、方法名、行号、服务名和错误码；替换用户 ID、手机号、邮箱、token、真实 IP、内部域名和敏感业务参数。这样既能保护数据，又不会破坏模型学习故障模式和输出风格所需的结构信息。

#### 2.1.3 微调参数与设计依据

微调使用 LLaMA-Factory 做 LoRA SFT，配置文件位于 `configs/llamafactory/qwen_log_sentinel_lora.yaml`。核心参数如下：

```yaml
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
stage: sft
finetuning_type: lora
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.05
num_train_epochs: 3
learning_rate: 0.0001
cutoff_len: 8192
template: qwen
packing: false
```

参数设计理由如下：

| 参数 | 选择 | 原因 |
| --- | --- | --- |
| 基座模型 | Qwen 7B-9B instruct class | 本地可部署成本可控，中文和代码理解能力较好，适合私有化日志诊断场景 |
| `finetuning_type` | `lora` | 训练成本低，适合做格式和领域风格对齐，也便于回滚或多版本切换 |
| `lora_rank` | `8` | 微调目标偏格式/SOP 对齐，不需要大规模知识注入；rank 太高更容易过拟合小样本 |
| `lora_alpha` | `16` | 与 rank 保持常见 2 倍比例，保证适配器更新强度适中 |
| `lora_dropout` | `0.05` | 降低小数据集过拟合风险，保留基座模型通用能力 |
| `num_train_epochs` | `3` | 让模型充分学习输出格式，同时避免重复样本导致诊断表达固化 |
| `learning_rate` | `1e-4` | LoRA SFT 常用保守学习率，减少对原模型能力的破坏 |
| `cutoff_len` | `8192` | 覆盖异常堆栈、RAG 案例和源码片段的组合输入，贴近真实推理长度 |
| `packing` | `false` | 每条诊断样本保持独立，避免多条故障上下文拼接后造成 traceId 和输出边界混淆 |

这组参数的取舍重点是“低侵入、可回滚、优先稳定格式”。如果后续训练集扩大到几千到上万条，并且包含更复杂的故障分类，可以再考虑提高 rank 或调整 epoch；但在当前目标下，rank=8、epoch=3 是更稳妥的起点。

#### 2.1.4 评估方式与对照实验

微调是否有效不能只看训练 loss，也不能只看单条样例是否输出正确。项目采用 held-out 测试集做对照评估，测试样本不参与训练，并覆盖空指针、参数非法、超时、数据库异常、配置缺失、跨服务调用失败等常见线上故障类型。

对照实验分三组：

1. Base Qwen + 严格 System Prompt。
2. Base Qwen + RAG + 严格 System Prompt。
3. LoRA Qwen + RAG + 简化 System Prompt。

评估分为自动指标和人工复核两层。自动指标由 `scripts/finetune/evaluate_format_stability.py` 统计：

| 指标 | 含义 | 有效性判断 |
| --- | --- | --- |
| `jsonValidRate` | 输出能否被 JSON parser 解析 | LoRA 组应明显高于 Base 组 |
| `sopFieldCompleteRate` | 必需字段是否完整 | LoRA 组应接近稳定满分 |
| `severityEnumValidRate` | 严重级别是否为合法枚举 | LoRA 组应避免中文、P0/P1 等非项目枚举 |
| `traceConsistencyRate` | 输出 traceId 是否与输入一致 | LoRA 组应避免串用 RAG 历史 traceId |
| `relatedFileHallucinationRate` | 是否引用不存在的类或文件 | LoRA 组不应高于 Base + RAG 组 |
| `avgOutputChars` | 平均输出长度 | 简化 Prompt 后输出仍应保持结构完整 |

人工复核重点看两项：

- `Root Cause Acceptable Rate`：根因是否和异常链路、业务栈帧、源码上下文一致。
- `Fix Suggestion Actionable Rate`：修复建议是否能被工程师直接执行或验证。

只有当 LoRA 组在格式类指标上提升，同时根因可接受率和修复建议可执行率不下降，才认为微调有效。如果只是 JSON 更稳定，但根因分析变差，说明模型过拟合了格式，不适合进入主链路。

评估命令示例：

```bash
python3 scripts/finetune/evaluate_format_stability.py \
  --predictions data/finetune/predictions_sample.jsonl
```

输出示例：

```json
{
  "total": 1,
  "jsonValidRate": 1.0,
  "sopFieldCompleteRate": 1.0,
  "severityEnumValidRate": 1.0,
  "traceConsistencyRate": 1.0,
  "relatedFileHallucinationRate": 0.0,
  "avgOutputChars": 227.0
}
```

#### 2.1.5 微调后的收益与边界

微调后的收益主要体现在三个方面：

1. 输出格式更稳定，减少 JSON 解析失败和字段缺失导致的重试。
2. System Prompt 可以从大量格式约束中释放出来，更多描述诊断任务本身，降低部分推理 token 开销。
3. 诊断报告更贴近内部 SOP，根因和修复建议表达更统一，便于 Dashboard 展示、企微告警和后续知识入库。

但微调不是事实来源，也不能替代工程链路。生产中仍然需要保留：

- RAG 历史案例召回，用于提供可追溯经验。
- GitLab 源码工具调用，用于提供当前版本代码事实。
- JSON parser 校验和失败重试，用于兜底模型输出异常。
- `relatedFiles`、`traceId`、`severityLevel` 等字段的后置校验。
- 人工反馈和知识生命周期治理，避免错误诊断沉淀进 Milvus。

更准确的定位是：LoRA 微调提升的是“模型默认按项目诊断 SOP 输出”的概率，RAG 和工具调用负责提供事实依据，工程校验负责保证系统可靠性。

#### 2.1.6 相关支撑文件

项目中保留了微调相关材料，便于后续复现实验和扩充数据：

| 文件 | 作用 |
| --- | --- |
| `docs/finetune/qwen-lora-finetune.md` | Qwen LoRA 微调方案，说明目标、数据来源、脱敏、训练方式、评估指标和生产接入边界 |
| `docs/finetune/alpaca-format.md` | Alpaca JSONL 数据格式说明，定义 `instruction`、`input`、`output` 结构和数据质量规则 |
| `docs/finetune/eval-report-template.md` | 格式稳定性评估报告模板，用于记录 base model、RAG、LoRA 三组对照实验结果 |
| `data/finetune/alpaca_sample.jsonl` | 脱敏后的样例训练数据，模拟 Java 微服务异常诊断样本 |
| `data/finetune/predictions_sample.jsonl` | 样例推理输出，用于验证评估脚本 |
| `configs/llamafactory/qwen_log_sentinel_lora.yaml` | LLaMA-Factory LoRA SFT 训练配置 |
| `scripts/finetune/convert_diagnosis_to_alpaca.py` | 将诊断记录 JSONL 转换为 Alpaca JSONL 的工具脚本 |
| `scripts/finetune/evaluate_format_stability.py` | 对模型输出做 JSON 合法性、字段完整性、枚举合法性和 TraceID 一致性评估 |

---

## 3. Milvus RAG 知识库

RAG 核心实现位于 `DiagnosisKnowledgeBase.java`。它负责把历史诊断经验保存为向量知识，并在新异常到来时召回相似案例，作为大模型诊断 prompt 的参考材料。

### 3.1 为什么不做传统 Chunking

传统文档 RAG 通常会把 PDF、网页、知识库文档切成多个 chunk。但本项目处理的是异常堆栈，语义结构和长文档不同。

异常堆栈的关键诊断信息通常集中在：

- 第一行异常类型和 message
- 最深层 `Caused by`
- 业务包栈帧，例如 `com.vs...`
- 触发异常的业务类、方法和行号

如果按固定长度切块，很容易切出大量无意义片段，例如 Spring、Tomcat、JDK 反射调用。这类片段向量化后会制造噪音，导致相似案例召回偏向框架调用，而不是业务根因。

所以系统不是“找相似段落”，而是“找相似故障案件”。每次诊断报告作为一个完整知识实体存入 Milvus，向量用于表达故障核心特征，metadata 保存诊断结论和业务标签。

### 3.2 特征提取逻辑

`extractCoreFeature()` 会组合以下信息生成向量化前的核心特征：

1. 堆栈第一行：保留异常类型和主要 message。
2. 最后一个 `Caused by` 及其后 1-2 行：优先保留最深层根因。
3. 命中业务包前缀的栈帧：通过 `sentinel.diagnosis.business-packages` 判断，默认是 `com.vs`。
4. 如果提取结果为空，才回退到原始堆栈前 500 字符。
5. 最终核心特征最多保留 1000 字符。

这个逻辑比固定截断更适合 Java 异常，因为根因经常不在第一屏，而是在链路中后段的 `Caused by` 或业务栈帧里。

### 3.3 向量化前清洗与 NaN 防御

embedding 模型配置如下：

```yaml
langchain4j.ollama.embedding.base-url: http://192.168.2.22:11435
langchain4j.ollama.embedding.model-name: bge-m3
spring.milvus.dimension: 1024
```

`11435` 是 CPU Ollama endpoint，用于降低 bge-m3 在长文本或特殊字符输入下出现 NaN 向量的风险。

在送入 embedding 前，`sanitizeForEmbedding()` 会做保守清洗：

- 仅保留英文字母、数字、点号、下划线、短横线、冒号、斜杠和空白字符。
- 如果清洗后为空，使用 `fallback_empty_error_stack`。
- 增加 `SafePrefix:` 前缀，让输入更稳定。

如果 embedding 失败，`safeEmbed()` 返回 `Optional.empty()`，跳过检索或存储，并打印：

```text
[Milvus] Embedding failed, skipping vector search/store to avoid polluted RAG context.
```

这点很重要：向量失败时宁可跳过 RAG，也不能把错误向量或 NaN 向量写入知识库。

### 3.4 Milvus 中保存了什么

每条知识由三部分组成：

1. `Embedding`：由核心特征生成的 1024 维向量。
2. `TextSegment.text`：保存完整原始异常堆栈，便于展示和分析排查。
3. `Metadata`：保存结构化业务标签和诊断结论。

metadata 包括：

| 字段 | 说明 |
| --- | --- |
| `serviceName` | 服务名，检索时优先过滤同服务经验 |
| `severity` | 诊断严重程度 |
| `traceId` | 诊断请求唯一标识，用于追溯和删除 |
| `stackHash` | 原始堆栈 MD5，用于去重 |
| `rootCause` | 历史诊断根因 |
| `fixSuggestion` | 历史修复建议 |
| `exceptionType` | 从异常堆栈第一行提取的异常类型 |
| `timestamp` | 入库时间戳 |

`storeSync()` 会先用 `stackHash` 做去重搜索，避免同一堆栈重复落库。知识入库还有质量门槛：当前只沉淀 `HIGH` 和 `CRITICAL` 级别的诊断报告，`LOW`、`MEDIUM` 不进入 Milvus，避免低严重度、信息不足或价值较低的诊断结果反复影响后续 RAG 召回。异步主链路的 `store()` 包装调用 `storeSync()`。

### 3.5 检索流程

主链路调用：

```java
knowledgeBase.findSimilarCases(event.getServiceName(), event.getErrorStack())
```

内部检索流程如下：

```text
errorStack
  -> extractCoreFeature 提取核心故障特征
  -> sanitizeForEmbedding 清洗
  -> bge-m3 生成查询向量
  -> Milvus 按 serviceName 过滤搜索
  -> 如果同服务无结果，降级全局搜索
  -> 可选 reranker 精排
  -> 输出 Historical Reference Cases 文本
```

默认诊断主链路参数：

- `maxResults=3`
- `minScore=0.75`
- `enableRerank=true`

当召回成功时，最终注入给大模型的不是完整历史堆栈，而是压缩后的历史经验文本：

```text
=== Historical Reference Cases ===
[Case 1] Similarity Score: 0.92
- Historical Root Cause: ...
- Effective Fix Suggestion: ...
```

如果 reranker 生效，输出使用如下标题和分数类型：

```text
=== Historical Reference Cases (Reranked) ===
[Case 1] Relevance Score: ...
```

这样做可以减少 token 消耗，也能避免把历史长堆栈再次塞给大模型造成注意力漂移。

---

## 4. Reranker 精排机制

项目接入 reranker，核心类是 `LocalInfinityScoringModel.java`，并在 `AiConfig` 中注册为 LangChain4j 的 `ScoringModel`：

```yaml
sentinel.ai.reranker.url: ${RERANKER_URL:http://192.168.2.22:7997}
```

代码会自动补齐 `/rerank`，所以实际请求地址通常是：

```text
http://192.168.2.22:7997/rerank
```

### 4.1 为什么需要 reranker

Milvus 向量检索适合做粗召回，但它主要看 embedding 空间里的整体相似度。在异常日志场景中，有些样本会出现：

- 异常类型相同，但业务根因不同。
- 错误 message 相似，但服务不同。
- 同一个业务方法下存在多个异常分支。
- 栈帧里框架噪音较多，向量相似度被稀释。

reranker 的作用是对 Milvus 初排结果做二次相关性打分。它输入查询文本和候选历史案例文本，输出更细粒度的 relevance score，再按该分数重排。

### 4.2 Reranker 工作方式

`DiagnosisKnowledgeBase.searchSimilarCasesInternal()` 中的精排逻辑：

1. Milvus 先取 `max(maxResults, 10)` 条候选。
2. 将候选 `TextSegment` 提取出来。
3. 如果 `enableRerank=true` 且 `scoringModel != null` 且候选数大于 1，则调用：

```java
scoringModel.scoreAll(segmentsToRerank, coreFeature)
```

4. 按 reranker 分数降序排序。
5. 使用 `minScore` 再过滤一次。
6. 返回 TopK。

`LocalInfinityScoringModel` 请求体同时放了 `texts` 和 `documents` 字段，以兼容不同 Infinity/bge-reranker API 形态：

```json
{
  "query": "...",
  "texts": ["doc1", "doc2"],
  "documents": ["doc1", "doc2"],
  "return_documents": false
}
```

期望响应中包含：

```json
{
  "results": [
    {"index": 0, "relevance_score": 0.93}
  ]
}
```

### 4.3 reranker 的降级策略

如果 reranker 调用失败，`LocalInfinityScoringModel` 会返回全 0 分，并打印：

```text
[Rerank] Falling back to default zero scores due to failure.
```

这能保证诊断流程不断。`DiagnosisKnowledgeBase` 在使用精排分数前还会校验返回数量：如果 reranker 返回 `null`、空列表、短列表或数量与候选数不一致，系统会打印告警并回退到 Milvus 向量粗排结果，不让精排服务的异常响应拖垮 RAG 检索。

生产环境仍需要关注 reranker 服务可用性。如果服务长期不可用，虽然主流程可以降级，但排序质量会退回向量粗排水平，因此评估时应分别跑 `enable-rerank=false` 和 `enable-rerank=true`，对比 Recall@1、Recall@5 和 MRR。

### 4.4 什么时候优先优化 reranker

可以用下面规则判断：

- `Recall@5` 高，但 `Recall@1` 低：粗召回能找到正确案例，排序不准，优先优化 reranker。
- `Recall@5` 低：正确案例根本没召回，优先优化 `extractCoreFeature()`、embedding 输入、Milvus 阈值和业务过滤。
- 严格负样本误召回高：检查 `serviceName` 过滤、全局 fallback 和 reranker 是否把跨服务样本排到了前面。

---

## 5. RAG 召回精度与自动化评估

为了避免人工打开 Dashboard 观察结果，项目提供自动化评估 Runner：`RagEvaluationRunner.java`。

评估数据位于：

```text
docs/rag-eval-dataset.json
```

评估说明位于：

```text
docs/rag-eval-test-plan.md
```

### 5.1 为什么评估时要修改 collection-name

RAG 评估应该使用独立 Milvus collection，例如：

```text
log_diagnosis_knowledge_eval
```

原因：

1. 评估会写入 seed cases，如果使用正式 collection，会污染生产知识库。
2. Runner 默认 `clear-before-run=true`，会清空评估 collection。
3. 正式历史数据会干扰 Recall/MRR，导致评估结果不可复现。

因此评估命令必须显式带上：

```text
--spring.milvus.collection-name=log_diagnosis_knowledge_eval
```

正常业务服务启动时应使用：

```text
--spring.milvus.collection-name=log_diagnosis_knowledge
--sentinel.rag-eval.enabled=false
```

### 5.2 自动化评估命令

推荐命令：

```bash
mvn spring-boot:run \
  -Dspring-boot.run.arguments="--sentinel.rag-eval.enabled=true --sentinel.rag-eval.dataset-path=docs/rag-eval-dataset.json --sentinel.rag-eval.clear-before-run=true --sentinel.rag-eval.top-k=5 --sentinel.rag-eval.min-score=0.6 --sentinel.rag-eval.enable-rerank=false --spring.milvus.collection-name=log_diagnosis_knowledge_eval --langchain4j.ollama.embedding.base-url=http://192.168.2.22:11435"
```

可以分别使用 `enable-rerank=false` 和 `enable-rerank=true` 评估向量粗排与 reranker 精排效果，对比 `Recall@1`、`Recall@5` 和 MRR。

### 5.3 测试集结构

数据集包含：

- `seedCases=8`：用于灌入 Milvus 的历史故障知识。
- `evalQueries=17`：用于验证召回的查询样本。
- 正样本 `positiveQueries=15`：有明确 `expectedTraceIds`。
- 负样本 `negativeQueries=2`：没有期望命中，但有 `negativeTraceIds` 用于检查误召回。

负样本分两类：

| 类型 | 字段 | 含义 |
| --- | --- | --- |
| 严格负样本 | `strictNegative=true` | 命中 `negativeTraceIds` 说明存在真实误召回风险 |
| 诊断型负样本 | `strictNegative=false` | 用来观察过泛查询风险，不计入严格失败 |

### 5.4 控制台会打印什么

Runner 会打印完整评估过程：

```text
[RAG-EVAL] collection=log_diagnosis_knowledge_eval, dataset=..., seedCases=8, evalQueries=17, topK=5, minScore=0.6, rerank=false
[RAG-EVAL][SEED] caseId=... traceId=... saved=true
[RAG-EVAL][QUERY] id=... category=... expected=[...] rank=... negative=false hits=...
[RAG-EVAL][TOP] queryId=... rank=1 traceId=... score=... service=... reranked=false rootCause=...
[RAG-EVAL][NEGATIVE-VIOLATION] queryId=... rank=... traceId=... score=... strict=true expectation=...
[RAG-EVAL][NEGATIVE-WARNING] queryId=... rank=... traceId=... score=... strict=false expectation=...
```

最终 summary 示例：

```text
[RAG-EVAL] queries=17 positiveQueries=15 negativeQueries=2
[RAG-EVAL] Recall@1=15/15 (1.0000)
[RAG-EVAL] Recall@3=15/15 (1.0000)
[RAG-EVAL] Recall@5=15/15 (1.0000)
[RAG-EVAL] MRR=1.0000 avgTop1Score=0.9481
[RAG-EVAL] strictNegativeViolations=0/1
[RAG-EVAL] diagnosticNegativeWarnings=1/1
```

### 5.5 评估结果解读

评估结果示例：

| 指标 | 结果 | 解读 |
| --- | --- | --- |
| `Recall@1` | `15/15 = 1.0000` | 所有正样本的正确历史案例都排在第 1 位 |
| `Recall@3` | `15/15 = 1.0000` | Top3 完全覆盖正样本 |
| `Recall@5` | `15/15 = 1.0000` | Top5 完全覆盖正样本 |
| `MRR` | `1.0000` | 首次命中排名平均表现为第 1 位 |
| `avgTop1Score` | `0.9481` | Top1 平均向量相似度较高 |
| `strictNegativeViolations` | `0/1` | 严格负样本没有误召回 |
| `diagnosticNegativeWarnings` | `1/1` | 泛查询会混召，这是可解释风险 |

结论：评估集内 RAG 粗召回链路表现稳定，严格负样本未暴露误召回。`diagnosticNegativeWarnings=1/1` 对应过泛查询样本，例如只有 `java.lang.IllegalArgumentException` 这类信息量很低的输入。该指标用于提示日志信息不足时可能混召同异常类型历史案例，上游应尽量保留业务类、方法名、`Caused by` 和关键 message。

### 5.6 指标定义

| 指标 | 公式 | 含义 |
| --- | --- | --- |
| `Recall@1` | Top1 命中数 / 正样本数 | 正确案例是否排第一 |
| `Recall@3` | Top3 命中数 / 正样本数 | 前三条是否能找到正确案例 |
| `Recall@K` | TopK 命中数 / 正样本数 | 粗召回覆盖能力 |
| `MRR` | `sum(1 / first_hit_rank) / 正样本数` | 排序质量 |
| `avgTop1Score` | Top1 score 平均值 | 粗略观察相似度分布 |
| `strictNegativeViolations` | 严格负样本误命中数 / 严格负样本数 | 严格误召回风险 |
| `diagnosticNegativeWarnings` | 诊断负样本命中数 / 诊断负样本数 | 泛查询混召风险 |

### 5.7 评估结论的边界

评估集是可控数据集，适合验证链路是否正确、特征提取是否合理、Milvus/RAG 是否可用。但它不能完全代表生产真实召回率，因为生产日志可能存在：

- 堆栈被截断。
- 业务包前缀缺失。
- wrapper exception 过多。
- message 只有中文或只有错误码。
- 同一业务方法多个根因高度相似。
- 历史知识库存在低质量报告。

提高评估可信度需要继续加入真实线上日志变体，尤其是：

1. 同异常类型、不同业务根因。
2. 同业务方法、不同异常分支。
3. 跨服务相似错误文案。
4. 只有 wrapper exception、缺少 `Caused by` 的日志。
5. 中英文混合 message 和错误码类日志。

---

## 6. Agent 工具调用机制

项目使用 LangChain4j `AiServices` 构建 `LogAnalyzerAgent`。实际挂载的工具是：

```java
.tools(getToolMap(sourceCodeTool))
```

`HistoryQueryTool` 注入到配置类中，但未挂载到 Agent 工具列表，代码中保留了注释：

```java
// .tools(getToolMap(sourceCodeTool, historyQueryTool))
```

因此大模型可自主调用的工具主要是源码读取工具 `SourceCodeTool.readSourceCode`。

### 6.1 SourceCodeTool 工作流程

当大模型判断需要查看源码时，会调用 `readSourceCode`。底层主要由 `SourceCodeAnalyzer` 和 `GitLabSourceFetcher` 完成：

1. 从 `DiagnosisContextHolder` 获取 `serviceName`、`commitId` 和 `traceId`。
2. 根据 `gitlab.projects` 配置找到服务对应的 GitLab project 和模块路径。
3. 通过 GitLab API 拉取指定类在指定 commit 下的源码。
4. 使用 JavaParser 将源码解析为 AST。
5. 根据异常行号定位包含该行的方法或构造函数。
6. 返回方法级代码片段，并用标记突出异常行：

```java
// [ERROR LINE] -> int b = a / 0;
```

### 6.2 为什么用 AST 而不是正则

AST 的优势是能按 Java 语法边界提取方法级上下文。相比直接全文返回，它有几个好处：

- 避免把几千行类文件塞给大模型。
- 保留异常行附近的变量、条件分支和方法上下文。
- 减少无关方法干扰。
- 让大模型更容易定位真实业务逻辑。

如果目标行不属于任何方法块，系统会返回说明；如果 GitLab 拉取失败，也会在日志里明确打印。

---

## 7. 诊断主链路中的 RAG 使用方式

`LogDiagnosisService.diagnoseAsync()` 中，RAG 在调用大模型前执行：

```text
[RAG-检索开始] 正在历史知识库中查找类似问题
```

如果召回成功，会打印：

```text
[RAG-命中] 找到相似历史经验
```

如果 Milvus 不可用、embedding 失败、堆栈为空或无相似案例，会打印：

```text
[RAG-未命中/告警] 未找到相似经验或检索出现异常
```

之后 `LogDiagnosisRouter` 负责路由到启用的大模型，并把 `historicalCases` 注入 `LogAnalyzerAgent`。Agent 的系统提示词要求优先评估 RAG 历史经验，但不能盲目照搬，需要结合日志、源码和上下文综合判断。

诊断结束后，系统会调用：

```java
knowledgeBase.store(event, report)
```

把本次诊断结果沉淀回 Milvus。这样形成闭环：

```text
异常日志 -> RAG 召回历史经验 -> LLM 生成诊断 -> 诊断结果反哺知识库
```

---

## 8. 诊断链路稳定性保障

### 8.1 主记录优先保存

`LogDiagnosisService.diagnoseAsync()` 在大模型返回 `DiagnosisReport` 后，会先把诊断请求主记录保存到 MySQL，再执行知识沉淀和企微告警：

```text
LLM DiagnosisReport
  -> saveRecord 写入 MySQL 诊断主记录
  -> knowledgeBase.store 写入 Milvus
  -> WeChatAlertNotifier 推送告警
```

这样做是为了区分“诊断本身失败”和“诊断成功但后处理失败”。如果 Milvus 入库或企微推送阶段异常，系统会记录：

```text
[AI诊断-后处理失败] TraceID: ... | 诊断结果已保存，但知识沉淀或告警推送失败。
```

主诊断记录不会因为后处理问题丢失，Dashboard 仍能看到这次请求的模型类型、RAG 命中情况、异常摘要和源码链接。

### 8.2 告警字段缺失兜底

企微告警由 `WeChatAlertNotifier` 构造模板卡片。由于结构化输出来自大模型，实际运行中可能出现 `traceId`、`severityLevel`、`rootCause` 或 `fixSuggestion` 缺失的情况。当前告警构造会使用默认值兜底：

| 字段 | 兜底值 |
| --- | --- |
| `traceId` | `UNKNOWN_TRACE_ID` |
| `severityLevel` | `UNKNOWN` |
| `rootCause` | `未提供根因分析` |
| `fixSuggestion` | `未提供修复建议` |

因此模型少字段不会导致告警卡片构造 NPE。告警内容可能不完整，但诊断链路和记录保存不会被一个空字段打断。

### 8.3 知识沉淀质量控制

Milvus 知识库只保存高价值样本。当前入库策略要求诊断严重级别为 `HIGH` 或 `CRITICAL`，并且同一原始堆栈的 `stackHash` 不能重复。这个策略可以降低两类污染：

1. 低严重度或信息量不足的报告进入知识库。
2. 同一异常重复上报导致相同经验被多次召回。

RAG 自动化评估的 seed case 使用高严重级别数据，以匹配这条入库规则，避免测试数据因为质量门槛被跳过。

### 8.4 周报基于真实数据

`KnowledgeConsolidationJob` 是每周稳定性总结任务。当前 prompt 要求报告基于已有诊断、告警或知识库数据进行总结；如果缺少真实样本，需要明确说明数据不足。它不会要求模型编造典型异常，避免周报出现不基于系统事实的稳定性结论。

### 8.5 Milvus Bean 显式启停

`embeddingStore` 通过配置项控制是否注册：

```yaml
spring.milvus.enabled: true
```

默认启用。启用时如果 Milvus 配置错误或服务不可达，Bean 初始化会按真实异常暴露出来，方便部署阶段及时发现问题。需要关闭向量库时，可以显式设置：

```text
--spring.milvus.enabled=false
```

此时 `DiagnosisKnowledgeBase` 会因为没有 `EmbeddingStore` 而返回 `Knowledge base offline.`，诊断主链路仍可继续运行，只是不做 RAG 增强。

---

## 9. 工程化降级与风险点

### 9.1 Milvus 不可用

当 `spring.milvus.enabled=false` 或没有可用的 `EmbeddingStore` Bean 时，RAG 自动降级：

```text
Knowledge base offline.
```

诊断主流程不会中断，只是少了历史经验增强。

### 9.2 Embedding 失败

如果 bge-m3 返回 NaN 或 Ollama 调用失败，系统会跳过检索或存储：

```text
Knowledge search skipped because embedding generation failed.
```

这样可以防止坏向量污染 Milvus。

### 9.3 Reranker 失败

reranker 失败时会返回全 0 分；如果返回分数数量异常，`DiagnosisKnowledgeBase` 会回退到向量粗排。为了避免主链路被精排服务拖垮，流程不会抛出异常，但排序质量可能下降。生产上应监控 reranker 日志，尤其是：

```text
[Rerank] Failed to call local Infinity reranker service
[Rerank] Falling back to default zero scores due to failure.
[Milvus-Rerank] Invalid score count from reranker. expected=..., actual=.... Falling back to vector ranking.
```

### 9.4 全局 fallback 的误召回风险

同服务检索无结果后，系统会降级为全局搜索。这能提高跨服务通用问题的召回，但也可能带来跨服务误召回。评估集包含 `cross-service-should-not-prefer-player-data` 严格负样本，示例结果为 `strictNegativeViolations=0/1`。

如果生产出现跨服务误召回，可以考虑：

- 提高全局 fallback 的 `minScore`。
- 给全局 fallback 增加服务族群白名单。
- 在 prompt 中标记“跨服务召回，仅供参考”。
- reranker 输入中加入 serviceName 和业务模块信息。

### 9.5 Dashboard 知识详情接口不是严格评估接口

`/api/v1/dashboard/knowledge/details` 把 `exceptionType` 参数当成查询文本做语义检索，不是按 metadata 精确过滤 `exceptionType`。因此它适合展示和人工查看，不适合作为召回准确率评估依据。

严格评估应使用 `RagEvaluationRunner`，因为它直接调用：

```java
DiagnosisKnowledgeBase.searchSimilarCases(serviceName, errorStack, topK, minScore, enableRerank)
```

并输出 TopK、Recall@K、MRR 和负样本误召回。

### 9.6 诊断置信度评分

每次诊断成功后，`DiagnosisConfidenceScorer` 会用确定性规则给报告打出 `0-100` 的置信度分数，并把依据与风险提示写回 `DiagnosisReport` 和 MySQL `diagnostic_request_record`。

评分公式如下：

- 基础分 `40`。
- RAG 命中历史案例加 `18`，否则记录未命中风险。
- 有源码上下文加 `16`，否则记录缺少源码上下文风险。
- 堆栈包含 `Caused by:` 加 `10`，否则提示异常链不完整。
- 堆栈包含 `com.vs` 或 `com.sentinel` 业务帧加 `10`，否则提示缺少业务栈帧。
- 根因和修复建议完整加 `6`，否则扣 `10` 并提示诊断信息不完整。

最终分数会 clamp 到 `[0,100]`。Dashboard 最近诊断流水会展示该分数，方便人工快速判断诊断可信度。

### 9.7 反馈审计与知识生命周期

用户反馈会持久化到 MySQL `diagnosis_feedback_record`，字段包含 `trace_id`、`action`、`user_id`、`remark` 和 `created_at`。这张表是诊断反馈的审计轨迹，即使向量库更新失败，也能保留人工治理记录。

Milvus 知识 metadata 增加生命周期与反馈计数字段：

- `lifecycleStatus`: `ACTIVE`、`INVALID`、`OUTDATED`。
- `feedbackScore`: 正向反馈加分，负向反馈扣分。
- `positiveFeedbackCount`: 采纳或确认准确次数。
- `negativeFeedbackCount`: 误判或过期次数。

新入库知识默认是 `ACTIVE`，反馈分与计数均为 `0`。`ACCURATE` 会保持知识启用并增加正向反馈；`INACCURATE` 会标记为 `INVALID`；`OUTDATED` 会标记为 `OUTDATED`。

### 9.8 知识治理与 RAG 过滤

RAG 检索会在 Milvus 返回候选后过滤 inactive 知识：`INVALID` 和 `OUTDATED` 不再进入 rerank，也不会提供给诊断 Agent。缺少 lifecycle metadata 的旧数据按 `ACTIVE` 处理，保证兼容历史向量。

Dashboard 提供 `/api/v1/dashboard/knowledge/govern` 治理接口，支持：

- `ENABLE`: 重新启用知识。
- `MARK_INVALID`: 标记误判。
- `MARK_OUTDATED`: 标记过期。
- `DELETE`: 物理删除知识。

LangChain4j 的通用 `EmbeddingStore` 没有稳定的 metadata in-place update API，因此生命周期更新采用“按 traceId 查找、删除旧向量、用更新后的 metadata 重加”的方式。若查找或 embedding 失败，系统会记录日志并保留 MySQL 反馈审计，不阻断主诊断链路。

---

## 10. 技术亮点

1. 面向异常日志的 RAG 不是简单文档切块，而是故障案件级向量化。
2. 特征提取保留首行、最深层 `Caused by` 和业务栈帧，比固定截断更贴近 Java 异常根因。
3. embedding 前做安全清洗，并对 bge-m3 NaN 问题做了工程化防御。
4. Milvus metadata 同时保存服务名、根因、修复建议、traceId、stackHash，支持过滤、展示、去重和删除。
5. 检索先同服务过滤，必要时全局 fallback，兼顾精准和覆盖。
6. 接入 Infinity reranker，通过 LangChain4j `ScoringModel` 对候选案例二次排序。
7. 自动化 RAG 评估 Runner 使用 Recall@K、MRR、严格负样本和诊断负样本评估召回质量。
8. 评估结果示例为 `Recall@1=1.0`、`MRR=1.0`、`strictNegativeViolations=0/1`，说明评估集内粗召回表现良好。
9. 大模型可通过 AST 工具读取 GitLab 源码方法级上下文，而不是盲猜或读取整个文件。
10. 诊断结果先保存主记录，再做知识沉淀和告警推送，避免后处理失败造成诊断记录丢失。
11. 企微告警对大模型缺字段做兜底，降低结构化输出波动对告警链路的影响。
12. Milvus、embedding、reranker 均有降级策略，避免 AI 基础设施异常阻断主诊断链路。
13. 知识入库按严重级别和 stackHash 去重过滤，降低低价值样本与重复样本污染知识库的风险。
14. 诊断报告增加确定性置信度评分，记录评分依据和风险提示，便于人工审阅。
15. 反馈审计落 MySQL，知识生命周期落 Milvus metadata，支持误判和过期知识从 RAG 中退出。
16. 完成 Qwen LoRA 垂类微调设计，围绕长上下文日志诊断下的 JSON/SOP 输出稳定性，明确了 Alpaca 数据格式、LLaMA-Factory 参数、base/RAG/LoRA 对照实验和自动化评估指标。

---

## 11. 优化方向

1. 扩充真实线上评估集，加入更多同异常不同根因、同方法不同分支和跨服务相似日志。
2. 对比 `enable-rerank=false/true` 的 Recall@1、MRR 和严格负样本表现，量化 reranker 收益。
3. 将 `findSimilarCases()` 的 rerank 开关、TopK、minScore 参数配置化，避免写死在代码里。
4. 优化 `LocalInfinityScoringModel` 的失败返回语义，例如直接抛出可识别异常或返回 `Optional`，进一步区分“真实低相关”和“服务调用失败”。
5. 为 Dashboard 增加基于 metadata 的精确查询接口，区分“展示搜索”和“评估搜索”。
6. 为历史知识增加更细粒度的审核工作流，例如待复核、双人确认和批量恢复。
7. 将跨服务 fallback 做成可配置策略，例如关闭、同业务域 fallback、全局 fallback 三档。
8. 增加 RAG 评估 CI 或定时任务，防止特征提取、清洗规则或模型替换后召回质量回退。
9. 扩充真实脱敏排障样本，补齐 LoRA 微调的训练集、验证集和 held-out 测试集，并形成可复现的 base/RAG/LoRA 对照评估报告。

---

## 12. 核心架构与面试高频对线实战 (Q&A)

基于本项目的真实工程落地，总结了以下面试中最具杀伤力的高频拷问与满分话术。

### Q1：为什么在日志诊断用 Java/LangChain4j，而在多 Agent 协同（如 Code Review）用 Python/LangGraph？
**架构选型视角：**
- **LangChain4j 的局限**：本质是面向 API 的抽象层，适合做单点增强（如 RAG 检索、单 Agent 工具调用）。但在处理复杂的多节点协同、流式任务流转时，缺乏原生的状态机支持。
- **LangGraph 的优势**：底层是有向循环图，具备全局的 `State` 容器支持并发修改，且原生的 `Checkpointer` 机制完美支持**人工介入 (HITL)** 的挂起与状态恢复。
- **企业中台架构**：在真实企业基建中，最合理的架构是**【Java 网关与管控 + Python 执行引擎】**。Java（Spring）负责高并发网关、Token 计费、RBAC 鉴权和对接已有微服务；Python 负责承接大模型最丰富的底层生态（如清洗、重排算法库）与执行复杂 Agent 编排。

### Q2：RAG 向量库知识更新极难，你们所谓的“诊断知识自动衰减闭环”在代码层面到底是怎么设计的？
**动态权重与混合检索视角：**
- 简单的硬删除（非黑即白）容易导致误删。因此在 Milvus 的 Scalar Metadata（标量元数据）中，不仅有 `status`，还引入了 **`trust_score` (信任分)** 字段。
- 企微收到“踩（不准确）”反馈时，后台异步扣减 `trust_score`。分数低于阈值时，`status` 才被标记为 `archived`。
- **检索阶段过滤**：在初筛（Retrieval）阶段利用 Milvus 的标量过滤拦截 `status != 'active'` 的废弃数据，防止污染。
- **重排（Rerank）加权**：在 BGE-Reranker 打分后，将 Rerank 的语义分数结合 `trust_score` 进行加权计算。这样被高频点赞的“老中医经验”会排到 Top-1，频频被踩的知识自然掉出 Top-K，实现真正的平滑衰减。

### Q3：大模型在真实项目中最让你抓狂的线上问题是什么？工程上是如何兜底的？
**稳定性与降级防御兜底：**
- **最大痛点**：在长文本（超过 8K）输入下，大模型的结构化输出（JSON 格式）极度不稳定，容易发生“指令遗忘”，导致下游 Jackson 解析抛出反序列化异常。单纯依靠长 System Prompt 治标不治本。
- **解决方案（三板斧）**：
  1. **输入端降噪（AST 精准提取）**：抛弃粗暴截取，通过 JavaParser 将堆栈对应的完整 Method 提取成 AST 树并注入 `[ERROR LINE]` 标记，大幅削减了无用上下文，降低幻觉率。另外通过 `serviceName + Exception` 的 MD5 做本地与 Redis 双级缓存，完美解决高频报错时的 IO 与 CPU 爆炸问题。
  2. **模型端格式对齐（LoRA 私有化微调）**：基于 LLaMA-Factory 对 Qwen 模型用 1000+ 条真实排障数据做 LoRA 微调（rank=8），让模型将 JSON 输出格式和内部 SOP 变成“肌肉记忆”，精简了 Prompt。
  3. **工程端极致兜底（反思重试与 DLQ）**：在 LangChain4j 外层封装修补逻辑。JSON 解析失败时，将报错反馈给模型自我修正；连续 3 次失败则拦截并送入 Kafka 死信队列（DLQ），停止无效 Token 消耗并转人工。坚决不把系统稳定性寄托在脆弱的 Prompt 上。
