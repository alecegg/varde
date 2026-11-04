// Pure mapping from SDK messages to contract events: [{event, data}].

const tokenFields = (usage = {}) => ({
  input_tokens: usage.input_tokens ?? usage.inputTokens ?? 0,
  output_tokens: usage.output_tokens ?? usage.outputTokens ?? 0,
  cache_read_input_tokens: usage.cache_read_input_tokens ?? usage.cacheReadInputTokens ?? 0,
  cache_creation_input_tokens:
    usage.cache_creation_input_tokens ?? usage.cacheCreationInputTokens ?? 0,
});

export function usageEvent(result) {
  const modelUsage = {};
  let contextWindow = null;
  for (const [model, entry] of Object.entries(result.modelUsage ?? {})) {
    modelUsage[model] = {
      ...tokenFields(entry),
      cost_usd: entry.costUSD ?? 0,
      context_window: entry.contextWindow ?? null,
    };
    if (typeof entry.contextWindow === "number") {
      contextWindow = Math.max(contextWindow ?? 0, entry.contextWindow);
    }
  }
  return {
    event: "usage",
    data: {
      source: "claude",
      usage: tokenFields(result.usage),
      context_window: contextWindow,
      total_cost_usd: result.total_cost_usd ?? 0,
      model_usage: modelUsage,
    },
  };
}

function assistantEvents(message) {
  const events = [];
  if (message.error) {
    events.push({ event: "error", data: { message: `assistant error: ${message.error}` } });
  }
  for (const block of message.message?.content ?? []) {
    if (block?.type === "text") {
      events.push({ event: "text", data: { text: block.text ?? "" } });
    } else if (block?.type === "tool_use") {
      events.push({
        event: "tool_intent",
        data: { call_id: block.id ?? "", name: block.name ?? null, status: "running", input: block.input },
      });
    }
  }
  return events;
}

function toolResultEvents(message) {
  const content = message.message?.content;
  if (!Array.isArray(content)) return [];
  return content
    .filter((block) => block?.type === "tool_result")
    .map((block) => ({
      event: "tool_result",
      data: {
        call_id: block.tool_use_id ?? "",
        status: block.is_error ? "failed" : "completed",
        content: block.content,
      },
    }));
}

function resultEvents(message) {
  const failed = message.is_error === true || String(message.subtype ?? "").startsWith("error_");
  return [
    {
      event: "session_end",
      data: {
        status: failed ? "failed" : "completed",
        result: message.result ?? null,
        subtype: message.subtype ?? null,
      },
    },
    { event: "status", data: { status: "idle" } },
    usageEvent(message),
  ];
}

export function normalizeMessage(message) {
  switch (message?.type) {
    case "assistant":
      return assistantEvents(message);
    case "user":
      return toolResultEvents(message);
    case "result":
      return resultEvents(message);
    case "rate_limit_event":
      return [
        { event: "usage", data: { source: "claude", limit: message.rate_limit_info ?? message } },
      ];
    default:
      return [];
  }
}
