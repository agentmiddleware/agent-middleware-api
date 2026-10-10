import type { Tool, ToolExecutionOptions } from "ai";

/** A signed receipt returned by the Agent Middleware API. */
export interface AmwReceipt {
  receipt_id: string;
  outcome: string;
  [key: string]: unknown;
}

/** A permit minted by POST /v1/permits (subset of fields we use). */
export interface AmwPermit {
  permit_id: string;
  [key: string]: unknown;
}

export interface AmwClientOptions {
  /** API base URL. Defaults to https://api.thisisatest.tech . */
  baseUrl?: string;
  /** API key. Falls back to the AMW_API_KEY environment variable. */
  apiKey?: string;
  /** Wallet that issues permits and is charged for tool calls. */
  issuerWalletId: string;
  /** Wallet the permit encumbers. Defaults to the issuer wallet. */
  subjectWalletId?: string;
  /** Credit cap per permit, as a decimal string. Defaults to "25". */
  maxCredits?: string;
  /** Permit lifetime in seconds. Defaults to 300. */
  expiresInSeconds?: number;
  /** OAuth scopes to request on the permit. Defaults to []. */
  scopes?: string[];
  /** Custom fetch implementation (used by tests). */
  fetchFn?: typeof fetch;
}

/** Error thrown when a permit is denied. The tool is never dispatched. */
export class PermitDeniedError extends Error {
  readonly code = "permit_denied";
  constructor(
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "PermitDeniedError";
  }
}

/** Error thrown when the governed invoke fails. Carries the server receipt when one was returned. */
export class GovernedInvokeError extends Error {
  readonly code = "governed_invoke_failed";
  constructor(
    message: string,
    readonly receipt?: AmwReceipt | null,
    readonly payload?: unknown,
  ) {
    super(message);
    this.name = "GovernedInvokeError";
  }
}

/** Minimal JSON-RPC envelope subset returned by POST /mcp/messages. */
interface McpEnvelope {
  result?: {
    content?: Array<{ type?: string; text?: string; [k: string]: unknown }>;
    isError?: boolean;
    error?: unknown;
    structuredContent?: Record<string, unknown>;
    receipt?: AmwReceipt;
  };
  error?: {
    message?: string;
    code?: number;
    data?: { receipt?: AmwReceipt; [k: string]: unknown };
  };
}

const DEFAULT_BASE_URL = "https://api.thisisatest.tech";

function randomKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return `amw-${Date.now()}-${Math.floor(Math.random() * 1e12)}`;
}

export class AmwClient {
  readonly baseUrl: string;
  private readonly apiKey: string;
  readonly issuerWalletId: string;
  readonly subjectWalletId: string;
  readonly maxCredits: string;
  readonly expiresInSeconds: number;
  readonly scopes: string[];
  private readonly fetchFn: typeof fetch;

  constructor(options: AmwClientOptions) {
    const apiKey = options.apiKey ?? process.env["AMW_API_KEY"] ?? "";
    if (!apiKey) {
      throw new Error("An API key is required: pass apiKey or set AMW_API_KEY.");
    }
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.apiKey = apiKey;
    this.issuerWalletId = options.issuerWalletId;
    this.subjectWalletId = options.subjectWalletId ?? options.issuerWalletId;
    this.maxCredits = options.maxCredits ?? "25";
    this.expiresInSeconds = options.expiresInSeconds ?? 300;
    this.scopes = options.scopes ?? [];
    this.fetchFn = options.fetchFn ?? fetch;
  }

  private async postJson(path: string, body: unknown, idempotencyKey?: string): Promise<unknown> {
    const headers: Record<string, string> = {
      "X-API-Key": this.apiKey,
      "Content-Type": "application/json",
    };
    if (idempotencyKey) {
      headers["Idempotency-Key"] = idempotencyKey;
    }
    const res = await this.fetchFn(`${this.baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) {
      const detail =
        typeof data === "object" && data !== null && "detail" in data
          ? String((data as { detail: unknown }).detail)
          : `http_${res.status}`;
      throw new GovernedInvokeError(detail, null, data);
    }
    return data;
  }

  /** Mint a permit scoped to one tool. Uses POST /v1/permits with a caller-owned idempotency key. */
  async createPermit(toolName: string, idempotencyKey: string): Promise<AmwPermit> {
    const expiresAt = new Date(Date.now() + this.expiresInSeconds * 1000).toISOString();
    try {
      const data = (await this.postJson(
        "/v1/permits",
        {
          issuer_wallet_id: this.issuerWalletId,
          subject_wallet_id: this.subjectWalletId,
          allowed_tools: [toolName],
          max_credits: this.maxCredits,
          expires_at: expiresAt,
          scopes: this.scopes,
        },
        idempotencyKey,
      )) as AmwPermit;
      if (!data || typeof data.permit_id !== "string") {
        throw new GovernedInvokeError("invalid_permit_response", null, data);
      }
      return data;
    } catch (err) {
      if (err instanceof GovernedInvokeError && err.message.startsWith("permit_")) {
        throw new PermitDeniedError(err.message, err.payload);
      }
      throw err;
    }
  }

  /** Ask POST /v1/permits/verify whether this permit admits this tool call. */
  async verifyPermit(permitId: string, toolName: string): Promise<{ valid: boolean; reason?: string }> {
    const data = (await this.postJson("/v1/permits/verify", {
      permit_id: permitId,
      wallet_id: this.subjectWalletId,
      tool: toolName,
    })) as { valid?: boolean; reason?: string | null };
    return { valid: data.valid === true, reason: data.reason ?? undefined };
  }

  /**
   * Dispatch one governed tool call through POST /mcp/messages (tools/call).
   * The server runs the tool under the permit and returns a signed receipt.
   */
  async invokeTool(args: {
    toolName: string;
    toolArgs: Record<string, unknown>;
    permitId: string;
    idempotencyKey: string;
  }): Promise<{ output: unknown; receipt: AmwReceipt }> {
    const envelope = (await this.postJson(
      "/mcp/messages",
      {
        jsonrpc: "2.0",
        id: args.idempotencyKey,
        method: "tools/call",
        params: {
          name: args.toolName,
          arguments: args.toolArgs,
          mcpContext: {
            wallet_id: this.subjectWalletId,
            permit_id: args.permitId,
            idempotency_key: args.idempotencyKey,
          },
        },
      },
      args.idempotencyKey,
    )) as McpEnvelope;

    if (envelope.error) {
      const receipt = envelope.error.data?.receipt ?? null;
      const message = envelope.error.message ?? "mcp_call_failed";
      if (message.startsWith("permit_")) {
        throw new PermitDeniedError(message, envelope);
      }
      throw new GovernedInvokeError(message, receipt, envelope);
    }
    const result = envelope.result;
    if (!result || typeof result !== "object") {
      throw new GovernedInvokeError("invalid_mcp_result", null, envelope);
    }
    if (!result.receipt || typeof result.receipt.receipt_id !== "string") {
      throw new GovernedInvokeError("missing_receipt", null, envelope);
    }
    if (result.isError === true) {
      const message =
        typeof result.error === "string" && result.error ? result.error : "mcp_tool_error";
      throw new GovernedInvokeError(message, result.receipt, envelope);
    }
    const output = result.structuredContent ?? result.content ?? null;
    return { output, receipt: result.receipt };
  }
}

/** Options accepted by governedTool. */
export interface GovernedToolOptions extends AmwClientOptions {
  /**
   * Server-side MCP tool name to invoke. The tool must be registered on the
   * Agent Middleware API under this name; the wrapper keeps the AI SDK tool's
   * description and schema but dispatches execution through the governed path.
   */
  toolName: string;
  /**
   * Build the idempotency key for a call. Defaults to deriving it from the
   * AI SDK toolCallId (amw-<toolCallId>) so retries of the same model-issued
   * tool call reuse the key; falls back to a random key when absent.
   */
  idempotencyKeyFor?: (input: unknown, execOptions?: ToolExecutionOptions) => string;
}

/** A governed AI SDK tool with the receipt of its most recent call attached. */
export type GovernedTool = Tool & {
  /** Receipt returned by the server for the most recent governed call. */
  lastReceipt: AmwReceipt | null;
};

function defaultKeyFor(_input: unknown, execOptions?: ToolExecutionOptions): string {
  const callId = execOptions?.toolCallId;
  if (typeof callId === "string" && callId.length > 0) {
    return `amw-${callId}`.slice(0, 128);
  }
  return randomKey();
}

/**
 * Wrap an AI SDK tool() so every execution follows the permit before action,
 * receipt after rule: mint a permit (POST /v1/permits), check admission
 * (POST /v1/permits/verify), then dispatch through the governed invoke path
 * (POST /mcp/messages tools/call) which runs the tool and returns a receipt.
 * A denied permit throws PermitDeniedError before anything is dispatched.
 */
export function governedTool(baseTool: Tool, options: GovernedToolOptions): GovernedTool {
  const { toolName, idempotencyKeyFor, ...clientOptions } = options;
  if (!toolName) {
    throw new Error("governedTool requires a toolName matching a server-side MCP tool.");
  }
  const client = new AmwClient(clientOptions);
  const keyFor = idempotencyKeyFor ?? defaultKeyFor;

  const wrapped = {
    ...baseTool,
    lastReceipt: null as AmwReceipt | null,
    async execute(input: unknown, execOptions?: ToolExecutionOptions): Promise<unknown> {
      const idempotencyKey = keyFor(input, execOptions);
      const permit = await client.createPermit(toolName, `permit-${idempotencyKey}`.slice(0, 128));
      const verdict = await client.verifyPermit(permit.permit_id, toolName);
      if (!verdict.valid) {
        throw new PermitDeniedError(verdict.reason ?? "permit_denied", verdict);
      }
      const args =
        input !== null && typeof input === "object"
          ? (input as Record<string, unknown>)
          : { value: input };
      try {
        const { output, receipt } = await client.invokeTool({
          toolName,
          toolArgs: args,
          permitId: permit.permit_id,
          idempotencyKey,
        });
        wrapped.lastReceipt = receipt;
        return output;
      } catch (err) {
        if (err instanceof GovernedInvokeError && err.receipt) {
          wrapped.lastReceipt = err.receipt;
        }
        throw err;
      }
    },
  };
  return wrapped as unknown as GovernedTool;
}
