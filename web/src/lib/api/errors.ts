export class FrontendApiError extends Error {
  status?: number;
  code: string;

  constructor(message: string, options: { status?: number; code?: string } = {}) {
    super(message);
    this.name = "FrontendApiError";
    this.status = options.status;
    this.code = options.code ?? "UNKNOWN";
  }
}

const STATUS_MESSAGES: Record<number, string> = {
  401: "登录状态已失效，请重新登录。",
  403: "当前账号无权访问该订单或执行此操作。",
  404: "未找到相关订单、用户或会话。",
  422: "请求信息不完整，请检查后重试。",
  429: "请求过于频繁，请稍后重试。",
  500: "服务暂时不可用，请稍后重试。",
  503: "智能服务暂时不可用，请稍后重试。",
};

export function messageForStatus(status: number): string {
  return STATUS_MESSAGES[status] ?? (status >= 500 ? STATUS_MESSAGES[500] : "请求失败，请稍后重试。");
}

export function toUserMessage(error: unknown): string {
  if (error instanceof FrontendApiError) return error.message;
  if (error instanceof DOMException && error.name === "AbortError") return "消息接收中断，请重新发送。";
  if (error instanceof TypeError) return "无法连接售后服务，请检查后端是否正常运行。";
  return "服务暂时不可用，请稍后重试。";
}

export function modelServiceError(): FrontendApiError {
  return new FrontendApiError("智能服务暂时不可用，请稍后重试。", { status: 503, code: "MODEL_SERVICE_ERROR" });
}

export function streamInterruptedError(): FrontendApiError {
  return new FrontendApiError("消息接收中断，请重新发送。", { code: "STREAM_INTERRUPTED" });
}
