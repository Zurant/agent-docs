import re

with open('docs/prep/ai-agent.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove Mermaid blocks and JSON blocks (which are the examples)
# Example 1.1 Trace: **典型执行轨迹 (Trace) 示例**：\n```mermaid...```
# Example 1.2: **工程示例 (Code Review 场景)**：\n```mermaid...```
# Example 1.3: **底层交互报文示例**：\n```json...```
# Example 1.4: **多 Agent 协同架构图示例**：\n```mermaid...```
# Example 2.3: **召回链路图示**：\n```mermaid...```

# Regex to remove lines starting with `**...示例**：` followed by a code block.
pattern = r'\*\*.*?[示图]例.*?\*\*：\s*```[a-z]*\n.*?```\n?'
content = re.sub(pattern, '', content, flags=re.DOTALL)

# Also there might be a few stray newlines. Let's fix multiple empty lines.
content = re.sub(r'\n{3,}', '\n\n', content)

new_chapter = """
## 0. 大模型基础概念 (夯实地基)

在开始复杂的 Agent 架构前，必须深刻理解大模型的底层运作机制，这是防范线上幻觉与排查性能瓶颈的基石。

### 0.1 Token 与 Context Window (上下文窗口)

- **Token**：大语言模型处理文本的基本单位。它可以是一个词、一个字或词的一部分（在英文中通常 1 个 Token 约等于 0.75 个单词；在中文中，根据分词策略，通常 1 个汉字可能占 1~2 个 Token）。大模型的计费和并发限制均以 Token 为准。
- **Context Window (上下文窗口)**：模型在一次交互中能“记住”并处理的最大 Token 数量（包含输入的 Prompt 和输出的生成内容）。
  - **痛点**：超出窗口上限会导致模型直接截断遗忘，或产生严重的幻觉（“中间遗忘”效应）。因此在 RAG 或多轮对话中，我们必须进行 Chunking 截断或摘要压缩。

### 0.2 解码参数 (Temperature & Top-P)

大模型的输出不是确定的，而是基于概率分布采样的结果。通过调节这些参数，可以控制 AI 回答的“创造力”。
- **Temperature (温度)**：范围通常是 0 到 1（甚至更高）。
  - **值越低 (趋近 0)**：模型倾向于选择概率最高的词，回答非常确定、刻板。适合：**代码生成、数据结构化提取（如 JSON 输出）、RAG 知识问答**。
  - **值越高 (趋近 1)**：模型会引入更多随机性。适合：**文案创作、发散性头脑风暴**。
- **Top-P (核采样)**：模型在累积概率超过 P 的候选词汇中进行随机采样。通常与 Temperature 只调整其中一个即可。

### 0.3 角色设定 (System / User / Assistant)

在目前主流的 Chat 模式下，大模型接口（如 ChatML 规范）严格区分了不同的对话角色：
- **System (系统提示词)**：全局的最高指令，定义了模型的“人设”和不可逾越的“安全护栏”。它的权重最高，模型在回答时必须优先遵守。
- **User (用户输入)**：来自用户的实际提问或操作。这是产生“Prompt Injection (提示词注入)”攻击的重灾区。
- **Assistant (助手回复)**：模型过去返回的历史记录。将这些记录和前面的请求重新拼接，模型就能“回忆”起多轮对话的状态。

### 0.4 Embedding 向量 vs Fine-Tuning 微调

在企业落地 AI 时，最大的疑惑往往是“什么时候该用哪种技术”。
- **Embedding 向量 (RAG)**：将外部知识（如公司内部 Wiki、运维手册）转化为多维空间中的向量坐标，通过计算距离来匹配相关性。
  - **核心价值**：解决“不知道”的问题（补充外部新知识）。适合高频更新的动态数据。
- **Fine-Tuning 微调 (LoRA 等)**：修改模型内部的权重矩阵，让模型改变其行为模式或形成肌肉记忆。
  - **核心价值**：解决“不会做”的问题（规范输出格式或语气）。由于微调容易引发“灾难性遗忘”，它不适合用来强行灌输新知识。
  - **黄金法则**：**“知识边界用 RAG，格式与直觉用微调。”**
"""

# Now we need to insert `new_chapter` right after the `> [!NOTE]` block, and before `## 1.`
# And also we need to generate TOC.
# Let's find all headers.

parts = re.split(r'(## 1\. Agent 核心架构与模式)', content, maxsplit=1)
if len(parts) == 3:
    content = parts[0] + new_chapter + "\n" + parts[1] + parts[2]

# Generate TOC
headers = re.findall(r'^(##+)\s+(.*)$', content, flags=re.MULTILINE)
toc_lines = ["## 目录", ""]
for hashes, title in headers:
    if title == "目录": continue
    level = len(hashes) - 2
    if level < 0: continue
    indent = "  " * level
    # Github markdown link conversion: lowercase, replace spaces with hyphens, remove punctuation
    link = re.sub(r'[^\w\s-]', '', title.lower()).replace(' ', '-')
    toc_lines.append(f"{indent}- [{title}](#{link})")
toc_lines.append("")

toc_str = "\n".join(toc_lines)

# Insert TOC right before `## 0.`
parts2 = re.split(r'(## 0\. 大模型基础概念)', content, maxsplit=1)
if len(parts2) == 3:
    content = parts2[0] + toc_str + "\n" + parts2[1] + parts2[2]

with open('docs/prep/ai-agent.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("Processing complete.")
