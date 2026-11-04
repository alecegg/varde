import fs from "node:fs";
import { appendFileSync, readFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";

const configPath = process.env.VARDE_PI_DURABLE_FAKE_PROVIDER;
if (configPath) {
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  const originalWriteFile = fs.promises.writeFile.bind(fs.promises);
  fs.promises.writeFile = async (path, data, options) => {
    if (config.effectTarget && String(path) === config.effectTarget) {
      const handle = await fs.promises.open(path, "w");
      appendFileSync(config.effectStarted, "opened\n");
      try {
        await handle.writeFile(data, options);
      } finally {
        await handle.close();
      }
      return;
    }
    return originalWriteFile(path, data, options);
  };
  syncBuiltinESMExports();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.includes("/responses")) return realFetch(input, init);
    const request = JSON.parse(init.body ?? "{}");
    appendFileSync(config.requests, `${JSON.stringify(request)}\n`);
    const number = readFileSync(config.requests, "utf8").trim().split("\n").length;
    if (config.holdFirst && number === 1) {
      appendFileSync(config.started, "started\n");
      return await new Promise(() => {});
    }
    const tool = number === 1 ? config.firstTool : null;
    return new Response(streamResponse(tool, number, config.usage), {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    });
  };
}

function streamResponse(tool, number, usage) {
  const id = `resp_${number}`;
  const events = [
    { type: "response.created", response: { id, status: "in_progress" } },
  ];
  if (tool) {
    const call = { type: "function_call", id: `item_${number}`, call_id: `call_${number}`, name: tool.name, arguments: "" };
    events.push(
      { type: "response.output_item.added", output_index: 0, item: call },
      { type: "response.function_call_arguments.delta", output_index: 0, delta: JSON.stringify(tool.arguments) },
      { type: "response.function_call_arguments.done", output_index: 0, arguments: JSON.stringify(tool.arguments) },
      { type: "response.output_item.done", output_index: 0, item: { ...call, arguments: JSON.stringify(tool.arguments), status: "completed" } },
    );
  } else {
    const item = { type: "message", id: `item_${number}`, role: "assistant", phase: "final_answer", content: [] };
    events.push(
      { type: "response.output_item.added", output_index: 0, item },
      { type: "response.content_part.added", output_index: 0, content_index: 0, part: { type: "output_text", text: "" } },
      { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "fake reply" },
      { type: "response.output_text.done", output_index: 0, content_index: 0, text: "fake reply" },
      { type: "response.content_part.done", output_index: 0, content_index: 0, part: { type: "output_text", text: "fake reply" } },
      { type: "response.output_item.done", output_index: 0, item: { ...item, status: "completed", content: [{ type: "output_text", text: "fake reply", annotations: [] }] } },
    );
  }
  const output = tool
    ? [{ type: "function_call", id: `item_${number}`, call_id: `call_${number}`, name: tool.name, arguments: JSON.stringify(tool.arguments), status: "completed" }]
    : [{ type: "message", id: `item_${number}`, role: "assistant", phase: "final_answer", status: "completed", content: [{ type: "output_text", text: "fake reply", annotations: [] }] }];
  events.push({
    type: "response.completed",
    response: {
      id,
      status: "completed",
      output,
      usage: usage ?? { input_tokens: 2, output_tokens: 2, total_tokens: 4 },
    },
  });
  const bytes = new TextEncoder().encode(events.map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("") + "data: [DONE]\n\n");
  return new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } });
}
