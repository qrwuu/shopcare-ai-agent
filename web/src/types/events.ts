export type ChatStreamEvent =
  | { type: "message"; content: string }
  | { type: "process"; step: string; label: string; status: "running" | "completed" | "failed" }
  | { type: "tool_result"; tool: string; data: unknown }
  | { type: "interrupt"; interrupt_type: string; data: unknown }
  | { type: "final"; content: string }
  | { type: "error"; message: string };
