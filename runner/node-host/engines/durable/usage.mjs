import { calculateCost } from "@earendil-works/pi-ai/models";

export function usageEvent(message, models) {
  if (message.role !== "assistant" || !message.usage || !message.provider || !message.model) {
    return undefined;
  }
  const model = models?.getModel(message.provider, message.model);
  if (!model) return undefined;
  const usage = {
    ...message.usage,
    cost: { ...message.usage.cost },
  };
  const cost = calculateCost(model, usage);
  return {
    type: "usage",
    provider: message.provider,
    model: message.model,
    usage: {
      input: usage.input,
      output: usage.output,
      cacheRead: usage.cacheRead,
      cacheWrite: usage.cacheWrite,
      totalTokens: usage.totalTokens,
    },
    costUsd: cost.total,
  };
}
