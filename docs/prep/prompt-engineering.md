# Prompt 工程 (Prompt Engineering)

Prompt 工程是 AI 与 Agent 开发的“输入控制层”，其核心在于通过精心设计的指令和上下文，激发大模型的推理能力、约束其行为输出，并引导其完成复杂的业务逻辑。

## 1. 基础范式
- **Zero-Shot (零样本)**: 不提供任何示例，直接依赖模型的预训练知识进行回答。适用于常识性任务或强泛化能力的基座模型。
- **Few-Shot (少样本 / In-Context Learning)**: 在 Prompt 中提供少量输入输出示例，引导模型理解特定的格式或复杂的业务逻辑。示例的选择与打分机制极大影响模型最终的输出质量。

## 2. 高级推理流 (Reasoning)
针对复杂逻辑和数学计算，单纯的指令往往不足，需要引导模型“思考过程”。
- **CoT (Chain of Thought, 思维链)**: 通过在 Prompt 中加入“Let's think step by step”或提供带有推理步骤的示例，强制模型显式地输出中间计算过程，大幅降低逻辑错误率。
- **ToT (Tree of Thoughts, 思维树)**: 当单一线性思考可能走入死胡同时，让模型在每一步生成多个分支选择，并对分支进行自我评估与回溯，寻找全局最优解。
- **GoT (Graph of Thoughts, 思维图)**: 更复杂的推理模式，允许思考步骤的合并、交叉与图结构的演化，适用于高度复杂的代码生成或长文本逻辑校验。

## 3. Agentic 工作流 (Agentic Workflow)
Prompt 工程不仅仅是对话，更是赋予模型调用工具和自主规划的能力。
- **ReAct (Reasoning and Acting)**: 经典的 Agent 范式，模型在每一步交替进行 `Thought` (思考) 和 `Action` (调用外部工具如搜索、API)，并根据 `Observation` (观察结果) 决定下一步。
- **Plan-and-Solve (规划与执行)**: 对于复杂任务，先让大模型生成一个全局的 Step-by-step Plan，然后逐个执行子任务。有效缓解长任务的“迷失”问题。
- **Reflection (自我反思)**: 模型在输出初步结果后，将其作为输入再进行一次自我审查与批判，发现错误并修正（如自我 Debug 代码）。

## 4. 生产级系统提示词设计
- **Meta-Prompting (元提示)**: 用提示词去生成或优化提示词。
- **Persona Injection (人设注入)**: 给模型赋予极其详尽的身份背景与知识边界约束（“你是一个拥有 10 年经验的资深 Java 架构师，你只回答后端技术问题……”）。
- **结构化输出约束**: 强约束模型必须输出标准 JSON 或 XML 格式，甚至结合 Regex 或 JSON Schema 在业务层进行拦截校验。

## 5. 安全与对齐防线
- **Prompt Injection (提示词注入防御)**: 防止恶意用户通过特定的 Prompt 覆盖或绕过系统原有的安全护栏，执行非授权操作（如数据泄露）。
- **Jailbreak 防御 (越狱防御)**: 设定清晰的边界，拒绝回答涉政、涉黄或具有破坏性的问题，保障 C 端/外部产品的合规底线。

## 6. Function Calling 与 Tool 底层调用机制 (源码级解析)

当面试官询问“Agent 的底层是如何把 Java 方法丢给大模型去调用的”，可以通过拆解主流框架（如 LangChain4j）的底层实现，展现资深的工程架构视角：

### 1. 扫描与识别（反射机制）
框架底层是通过 Java 的反射机制实现的。系统会拿到传入的 `Tool` 对象，遍历所有 `declaredMethods`，通过 `isAnnotationPresent(Tool.class)` 过滤出那些打上了 `@Tool` 注解的本地方法。

### 2. 生成大模型的“菜单”（元数据提取）
找到带有注解的方法后，框架会调用核心方法（如 `toolSpecificationFrom()`）进行“元数据提取”。
它会解析 Java 方法的**方法名**、**入参类型**（如 String, int），最关键的是提取 `@Tool("...")` 里的**描述文本（Description）**。随后，框架将这些元数据组装成 OpenAI 标准的 JSON Schema 格式（即 `ToolSpecification`）。这相当于给大模型提供了一份“API 菜单”，大模型依靠这个 Schema 来理解工具的作用及所需参数。

**大模型看到的“API 菜单”示例 (JSON Schema):**
```json
{
  "type": "function",
  "function": {
    "name": "get_user_info",
    "description": "根据用户 ID 查询用户的详细信息，如姓名、部门等。",
    "parameters": {
      "type": "object",
      "properties": {
        "user_id": {
          "type": "string",
          "description": "用户的唯一标识 ID，例如 'U12345'"
        }
      },
      "required": ["user_id"]
    }
  }
}
```

### 3. 组装本地执行器与动态映射
在组装完 `ToolSpecification` 后，代码会实例化一个执行器（如 `DefaultToolExecutor`），将目标对象和具体的方法引用封存起来，并以 `Map<ToolSpecification, ToolExecutor>` 的形式缓存。
当大模型推理完成并返回包含 `tool_calls` 的 JSON 时，框架会解析 JSON 中的函数名，去 Map 中匹配对应的 `ToolExecutor`，然后利用 Java 反射（`method.invoke`）去真正执行本地代码，最终将执行结果回调拼装给大模型。

**大模型决定调用工具时返回的 JSON 示例:**
```json
{
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "get_user_info",
        "arguments": "{\"user_id\": \"U12345\"}"
      }
    }
  ]
}
```

> [!TIP]
> **💡 进阶加分项：源码设计缺陷与落地避坑**
> 在阅读 LangChain4j 源码时可以发现，目前框架在绑定增强工具类时，往往只通过方法名（`m.getName().equals()`）和 `findFirst()` 来做匹配（源码注释中也留有 `TODO match by complete method signature`）。
> 
> **面试杀手锏话术**：“这意味着框架底层其实**不支持 Java 方法重载（Overload）**。如果有两个同名的 `@Tool` 方法，框架在组装 Executor 时可能会因为 `findFirst` 映射到错误的方法引用上，导致大模型回传参数时发生反射调用异常（如参数类型或数量不匹配）。因此我们在实际业务落地时，通过团队规范强制保证 Tool 方法命名唯一，或者在基础设施层对框架源码进行了重写兜底，这也是为什么纯调包无法满足工业级落地要求的原因。”
