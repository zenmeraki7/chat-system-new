export class ApiError extends Error {
  status: number;
  body: string;
  code?: string;
  userMessage?: string;
  requestId?: string;

  constructor(status: number, body: string, details?: { code?: string; userMessage?: string; requestId?: string }) {
    super(details?.userMessage || `${status} ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.code = details?.code;
    this.userMessage = details?.userMessage;
    this.requestId = details?.requestId;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
