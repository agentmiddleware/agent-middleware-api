/**
 * Minimal typed client for the gateway permit, call and receipt endpoints.
 *
 * Covered loop: discover tools, create a signed permit, invoke one governed
 * tool call, fetch and verify the signed receipt. No runtime dependencies,
 * uses the global fetch. Redirects are never followed, so a key cannot leak
 * to a redirect target. Revocation is live-checked server side, so an
 * exported permit or receipt must be rechecked here before relying on it.
 */
import {
  APIError,
  AuthenticationError,
  AuthorizationError,
  DeliveryUncertainError,
  IdempotencyConflictError,
  InsufficientFundsError,
  JsonObject,
  PermitDeniedError,
  TransportError,
} from "./errors.js";
import {
  InvocationResult,
  Permit,
  PermitRequestInput,
  Receipt,
  ReceiptVerification,
  ToolDefinition,
  parsePermit,
  parseReceipt,
  parseToolDefinition,
  permitRequestToPayload,
} from "./models.js";

export type FetchImpl = (url: string, init: RequestInit) => Promise<Response>;

export interface GatewayClientOptions {
  /** API key sent as X-API-Key. */
  apiKey: string;
  /** Gateway origin, e.g. http://127.0.0.1:8000 for a local quickstart. */
  baseUrl?: string;
  /** Per-request timeout in milliseconds. Defaults to 10000. */
  timeoutMs?: number;
  /** Optional bearer token for IGA-governed flows. Blank values are rejected locally. */
  bearerToken?: string;
  /** Fetch implementation, injectable for tests. Defaults to global fetch. */
  fetchImpl?: FetchImpl;
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_TIMEOUT_MS = 10_000;
const MAX_IDEMPOTENCY_KEY_LEN = 128;

export class GatewayClient {
  readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly bearerToken: string | null;
  private readonly fetchImpl: FetchImpl;

  constructor(options: GatewayClientOptions) {
    if (!options || typeof options.apiKey !== "string" || options.apiKey.length === 0) {
      throw new TypeError("apiKey must be a non-empty string");
    }
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    if (this.baseUrl.length === 0) {
      throw new TypeError("baseUrl must not be blank");
    }
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    if (options.bearerToken !== undefined) {
      const token = options.bearerToken.trim();
      if (token.length === 0) {
        throw new TypeError("bearerToken must not be blank; omit it to send no Authorization header");
      }
      this.bearerToken = token;
    } else {
      this.bearerToken = null;
    }
    const impl = options.fetchImpl ?? (globalThis.fetch as unknown as FetchImpl | undefined);
    if (typeof impl !== "function") {
      throw new TypeError("no fetch implementation available; pass fetchImpl explicitly");
    }
    this.fetchImpl = impl;
  }

  /** Caller-owned idempotency keys are validated before any request is sent. */
  static validateIdempotencyKey(key: string): string {
    if (typeof key !== "string") throw new TypeError("idempotencyKey must be a string");
    const trimmed = key.trim();
    if (trimmed.length === 0) throw new TypeError("idempotencyKey must not be blank");
    if (trimmed.length > MAX_IDEMPOTENCY_KEY_LEN) {
      throw new TypeError("idempotencyKey must be at most 128 characters");
    }
    return trimmed;
  }

  private static errorDetail(payload: JsonObject, fallback: string): string {
    const detail = payload.detail;
    if (typeof detail === "string" && detail.length > 0) return detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const nested = (detail as JsonObject).error ?? (detail as JsonObject).detail;
      if (typeof nested === "string" && nested.length > 0) return nested;
    }
    const error = payload.error;
    if (typeof error === "string" && error.length > 0) return error;
    return fallback;
  }

  private raiseHttpError(statusCode: number, payload: JsonObject, walletId: string | null): never {
    const detail = GatewayClient.errorDetail(payload, `HTTP ${statusCode}`);
    if (statusCode === 401) {
      throw new AuthenticationError(detail, statusCode, payload);
    }
    if (statusCode === 402) {
      const body = (payload.detail as JsonObject | undefined) ?? {};
      const shaped = body && typeof body === "object" && !Array.isArray(body) ? body : {};
      throw new InsufficientFundsError(walletId ?? "unknown", {
        shortfall: (shaped as JsonObject).shortfall,
        topUpUrl: (shaped as JsonObject).top_up_url,
        payload,
      });
    }
    if (statusCode === 403) {
      if (detail.startsWith("permit_")) throw new PermitDeniedError(detail, null, payload);
      throw new AuthorizationError(detail, statusCode, payload);
    }
    if (statusCode === 409) {
      throw new IdempotencyConflictError(detail, statusCode, payload);
    }
    throw new APIError(detail, statusCode, payload);
  }

  private async requestJson(
    method: string,
    path: string,
    opts: { walletId?: string | null; headers?: Record<string, string>; body?: unknown } = {},
  ): Promise<JsonObject> {
    const headers: Record<string, string> = {
      "X-API-Key": this.apiKey,
      "Content-Type": "application/json",
      "User-Agent": "amw-gateway-client/0.1.0",
      ...(opts.headers ?? {}),
    };
    if (this.bearerToken !== null) headers.Authorization = `Bearer ${this.bearerToken}`;
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        redirect: "manual",
        signal: AbortSignal.timeout(this.timeoutMs),
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      });
    } catch (err) {
      throw new TransportError(`${method} ${path} failed: ${err instanceof Error ? err.message : String(err)}`, {
        cause: err,
      });
    }
    if (response.status >= 300 && response.status < 400) {
      throw new TransportError(`redirect_blocked: ${method} ${path} answered ${response.status}`);
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new APIError("invalid_json_response", response.status);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new APIError("invalid_object_response", response.status);
    }
    const shaped = payload as JsonObject;
    if (!response.ok) {
      this.raiseHttpError(response.status, shaped, opts.walletId ?? null);
    }
    return shaped;
  }

  private parseReceiptField(data: unknown, responseName: string): Receipt {
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new APIError(`${responseName}_missing_receipt`);
    }
    try {
      return parseReceipt(data);
    } catch (err) {
      throw new APIError(`invalid_${responseName}_receipt: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  /** Return the executable tools advertised by the MCP gateway. */
  async discoverTools(): Promise<ToolDefinition[]> {
    const payload = await this.requestJson("GET", "/mcp/tools.json");
    const tools = payload.tools;
    if (!Array.isArray(tools) || !tools.every((tool) => tool && typeof tool === "object")) {
      throw new APIError("invalid_tools_response", null, payload);
    }
    try {
      return tools.map((tool) => parseToolDefinition(tool));
    } catch (err) {
      throw new APIError(`invalid_tools_response: ${err instanceof Error ? err.message : String(err)}`, null, payload);
    }
  }

  /** Create a signed permit using a caller-owned idempotency key. */
  async createPermit(request: PermitRequestInput, opts: { idempotencyKey: string }): Promise<Permit> {
    const key = GatewayClient.validateIdempotencyKey(opts.idempotencyKey);
    const payload = await this.requestJson("POST", "/v1/permits", {
      walletId: request.issuerWalletId,
      headers: { "Idempotency-Key": key },
      body: permitRequestToPayload(request),
    });
    try {
      return parsePermit(payload);
    } catch (err) {
      throw new APIError(`invalid_permit_response: ${err instanceof Error ? err.message : String(err)}`, null, payload);
    }
  }

  /** Invoke one MCP tool through the governed permit and receipt loop. */
  async invokeTool(
    name: string,
    args: JsonObject,
    opts: { walletId: string; permitId: string; idempotencyKey: string },
  ): Promise<InvocationResult> {
    const key = GatewayClient.validateIdempotencyKey(opts.idempotencyKey);
    const envelope = await this.requestJson("POST", "/mcp/messages", {
      walletId: opts.walletId,
      headers: { "Idempotency-Key": key },
      body: {
        jsonrpc: "2.0",
        id: key,
        method: "tools/call",
        params: {
          name,
          arguments: args,
          mcpContext: { wallet_id: opts.walletId, permit_id: opts.permitId, idempotency_key: key },
        },
      },
    });
    const error = envelope.error;
    if (error && typeof error === "object" && !Array.isArray(error)) {
      this.raiseMcpError(error as JsonObject, opts.walletId, envelope);
    }
    const result = envelope.result;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new APIError("invalid_mcp_result", null, envelope);
    }
    const shaped = result as JsonObject;
    const receipt = this.parseReceiptField(shaped.receipt, "mcp");
    if (receipt.outcome === "delivery_uncertain") {
      throw new DeliveryUncertainError(receipt.receiptId, "delivery_uncertain", envelope);
    }
    if (shaped.isError === true) {
      throw new APIError(typeof shaped.error === "string" ? shaped.error : "mcp_call_failed", null, envelope);
    }
    const content = shaped.content;
    if (!Array.isArray(content) || !content.every((item) => item && typeof item === "object")) {
      throw new APIError("invalid_mcp_content", null, envelope);
    }
    const structuredContent = shaped.structuredContent ?? null;
    if (structuredContent !== null && (typeof structuredContent !== "object" || Array.isArray(structuredContent))) {
      throw new APIError("invalid_mcp_structured_content", null, envelope);
    }
    return {
      content: content as JsonObject[],
      structuredContent: structuredContent as JsonObject | null,
      receipt,
      raw: shaped,
    };
  }

  private raiseMcpError(error: JsonObject, walletId: string, envelope: JsonObject): never {
    const reason = String(error.message ?? "mcp_call_failed");
    const data = error.data;
    const errorData = data && typeof data === "object" && !Array.isArray(data) ? (data as JsonObject) : {};
    const receiptData = errorData.receipt;
    const receipt =
      receiptData && typeof receiptData === "object" && !Array.isArray(receiptData)
        ? this.parseReceiptField(receiptData, "mcp_error")
        : null;
    const receiptId = receipt ? receipt.receiptId : null;
    const outcome = receipt ? receipt.outcome : null;
    if (outcome === "delivery_uncertain" || reason === "delivery_uncertain" || reason === "outcome_unknown") {
      if (!receiptId) throw new APIError("delivery_uncertain_without_receipt", null, envelope);
      throw new DeliveryUncertainError(receiptId, reason, envelope);
    }
    if (reason === "insufficient_funds" || outcome === "insufficient_funds") {
      throw new InsufficientFundsError(walletId, { receiptId, payload: envelope });
    }
    if (reason === "idempotency_in_progress" || reason === "idempotency_key_reused") {
      throw new IdempotencyConflictError(reason, 409, envelope);
    }
    if (reason.startsWith("permit_")) {
      throw new PermitDeniedError(reason, receiptId, envelope);
    }
    if (error.code === -32003) {
      throw new AuthorizationError(reason, 403, envelope);
    }
    throw new APIError(reason, null, envelope);
  }

  /** Fetch a wallet-authorized signed receipt. */
  async getReceipt(receiptId: string): Promise<Receipt> {
    const payload = await this.requestJson("GET", `/v1/receipts/${encodeURIComponent(receiptId)}`);
    return this.parseReceiptField(payload, "get");
  }

  /** Ask the gateway to verify a receipt signature and linkage. */
  async verifyReceipt(receiptId: string): Promise<ReceiptVerification> {
    const payload = await this.requestJson("POST", "/v1/receipts/verify", {
      body: { receipt_id: receiptId },
    });
    const receiptData = payload.receipt;
    const receipt =
      receiptData === null || receiptData === undefined
        ? null
        : this.parseReceiptField(receiptData, "verify");
    if (typeof payload.valid !== "boolean") {
      throw new APIError("invalid_receipt_verification", null, payload);
    }
    const reason = payload.reason;
    return {
      valid: payload.valid,
      reason: typeof reason === "string" ? reason : reason === null || reason === undefined ? null : String(reason),
      receipt,
      raw: payload,
    };
  }
}
