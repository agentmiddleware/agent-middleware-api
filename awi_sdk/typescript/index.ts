/**
 * AWI TypeScript SDK — Phase 8
 * TypeScript client for Agentic Web Interface (AWI) services
 *
 * Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"
 *
 * Proof surface note: the /v1/awi/* routes this client calls are frozen
 * proof surfaces. Production-like deployments leave them unmounted
 * (ENABLE_PROOF_SURFACES=false), so this client only works against a
 * server started with proof surfaces enabled. See docs/PROOF_SURFACES.md.
 */

import axios, { AxiosError, AxiosInstance, AxiosResponse } from "axios";

/** Default base URL, matching the Python SDK default. */
export const DEFAULT_BASE_URL = "http://localhost:8000";

export interface AWIConfig {
  baseUrl?: string;
  apiKey?: string;
  walletId?: string;
  timeout?: number;
}

/** Base class for typed API failures. Carries the axios response. */
export class AWIError extends Error {
  readonly status?: number;
  readonly detail: string;
  readonly response?: AxiosResponse;

  constructor(detail: string, response?: AxiosResponse) {
    super(detail);
    this.name = "AWIError";
    this.detail = detail;
    this.response = response;
    this.status = response?.status;
  }
}

/** The API returned an error status with no more specific mapping. */
export class AWIApiError extends AWIError {
  constructor(detail: string, response?: AxiosResponse) {
    super(detail, response);
    this.name = "AWIApiError";
  }
}

/** The API key was missing or invalid (HTTP 401). */
export class AWIAuthenticationError extends AWIError {
  constructor(detail: string, response?: AxiosResponse) {
    super(detail, response);
    this.name = "AWIAuthenticationError";
  }
}

/** The key is valid but may not perform this action (HTTP 403). */
export class AWIAuthorizationError extends AWIError {
  constructor(detail: string, response?: AxiosResponse) {
    super(detail, response);
    this.name = "AWIAuthorizationError";
  }
}

/** A governed call was refused by its permit (HTTP 403, permit error). */
export class AWIPermitDeniedError extends AWIAuthorizationError {
  constructor(detail: string, response?: AxiosResponse) {
    super(detail, response);
    this.name = "AWIPermitDeniedError";
  }
}

/** An idempotency key was reused for a different request (HTTP 409). */
export class AWIIdempotencyConflictError extends AWIError {
  constructor(detail: string, response?: AxiosResponse) {
    super(detail, response);
    this.name = "AWIIdempotencyConflictError";
  }
}

function errorCode(data: unknown): string {
  if (typeof data === "object" && data !== null && "error" in data) {
    const code = (data as Record<string, unknown>).error;
    return typeof code === "string" ? code : "";
  }
  return "";
}

function errorMessage(data: unknown, fallback: string): string {
  if (typeof data === "object" && data !== null) {
    const record = data as Record<string, unknown>;
    const message = record.message;
    if (typeof message === "string" && message) return message;
    const code = record.error;
    if (typeof code === "string" && code) return code;
  }
  if (typeof data === "string" && data) return data;
  return fallback;
}

/** Map an axios failure to the matching typed error, preserving .response. */
export function toAWIError(error: unknown): unknown {
  if (!axios.isAxiosError(error) || !error.response) return error;
  const response = error.response as AxiosResponse;
  const status = response.status;
  const data = response.data;
  const code = errorCode(data);
  const detail = errorMessage(data, (error as AxiosError).message);
  if (status === 401) return new AWIAuthenticationError(detail, response);
  if (status === 403) {
    if (code.startsWith("permit")) {
      return new AWIPermitDeniedError(detail, response);
    }
    return new AWIAuthorizationError(detail, response);
  }
  if (status === 409 && (code.includes("idempot") || code.includes("conflict"))) {
    return new AWIIdempotencyConflictError(detail, response);
  }
  return new AWIApiError(detail, response);
}

export interface AWISession {
  session_id: string;
  target_url: string;
  status: "created" | "active" | "paused" | "completed" | "failed";
  max_steps: number;
  step_count: number;
  created_at: string;
}

export interface AWIExecutionResult {
  execution_id: string;
  session_id: string;
  action: string;
  status: string;
  result?: Record<string, unknown>;
  error?: string;
  representation?: unknown;
  duration_ms?: number;
  cost_estimate?: number;
}

export interface AWIRepresentation {
  representation_id: string;
  representation_type: string;
  content: unknown;
  metadata: Record<string, unknown>;
  generated_at: string;
}

export type AWIAction =
  | "search_and_sort"
  | "add_to_cart"
  | "checkout"
  | "fill_form"
  | "login"
  | "logout"
  | "navigate_to"
  | "click_button"
  | "scroll"
  | "select_option"
  | "upload_file"
  | "extract_data"
  | "get_representation";

export type AWIRepresentationType =
  | "full_dom"
  | "summary"
  | "embedding"
  | "low_res_screenshot"
  | "accessibility_tree"
  | "json_structure"
  | "text_extraction";

export type AWIActionTier = "semantic" | "compatibility";
export type AWIActionStatus = "stable" | "provisional" | "deprecated";
export type AWIActionRiskLevel = "low" | "medium" | "high";

export interface AWIActionDefinition {
  action: AWIAction;
  category: string;
  description: string;
  parameters: Record<string, Record<string, unknown>>;
  required_preconditions: string[];
  postconditions: string[];
  estimated_cost: number;
  tier: AWIActionTier;
  status: AWIActionStatus;
  risk_level: AWIActionRiskLevel;
  sensitive_parameters: string[];
}

export interface AWIVocabulary {
  actions: AWIActionDefinition[];
  categories: string[];
}

/** Longest Idempotency-Key the governed AWI routes accept. */
export const MAX_IDEMPOTENCY_KEY_LENGTH = 128;

export interface AWIExecuteOptions {
  representation?: AWIRepresentationType;
  dryRun?: boolean;
  /** Permit authorizing tool `awi_execute`; sent as X-Permit-Id. */
  permitId: string;
  /** Caller-chosen key for this logical action; reuse it on retry. */
  idempotencyKey: string;
}

/**
 * AWI TypeScript Client
 *
 * @example
 * ```typescript
 * const client = new AWIClient({
 *   baseUrl: "https://api.example.com",
 *   apiKey: "your-key",
 *   walletId: "wallet-123"
 * });
 *
 * const session = await client.createSession("https://shop.example.com");
 * const result = await client.execute(
 *   session.session_id,
 *   "search_and_sort",
 *   { query: "laptops", sort_by: "price" },
 *   { permitId: "permit-from-POST-/v1/permits", idempotencyKey: "search-1" }
 * );
 * ```
 */
export class AWIClient {
  private client: AxiosInstance;
  private config: AWIConfig;

  constructor(config: AWIConfig = {}) {
    this.config = config;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (config.apiKey) {
      headers["X-API-Key"] = config.apiKey;
    }
    this.client = axios.create({
      baseURL: config.baseUrl || DEFAULT_BASE_URL,
      timeout: config.timeout || 30000,
      // Never follow redirects: axios forwards X-API-Key to the new host.
      maxRedirects: 0,
      headers,
    });
    // Surface typed errors while keeping the axios response attached.
    this.client.interceptors.response.use(undefined, (error: unknown) => {
      throw toAWIError(error);
    });
  }

  async discover(): Promise<AWIVocabulary> {
    const response: AxiosResponse = await this.client.get("/v1/awi/vocabulary");
    return response.data;
  }

  async createSession(
    targetUrl: string,
    options?: {
      maxSteps?: number;
      allowHumanPause?: boolean;
    }
  ): Promise<AWISession> {
    const response: AxiosResponse = await this.client.post("/v1/awi/sessions", {
      target_url: targetUrl,
      max_steps: options?.maxSteps ?? 100,
      allow_human_pause: options?.allowHumanPause ?? true,
      wallet_id: this.config.walletId,
    });
    return response.data;
  }

  /**
   * Execute an AWI action. POST /v1/awi/execute is governed: it requires a
   * permit (X-Permit-Id) and an Idempotency-Key. Throws before sending when
   * either is blank or the key is longer than 128 characters.
   */
  async execute(
    sessionId: string,
    action: AWIAction,
    parameters: Record<string, unknown> | undefined,
    options: AWIExecuteOptions
  ): Promise<AWIExecutionResult> {
    const permitId =
      typeof options?.permitId === "string" ? options.permitId.trim() : "";
    if (!permitId) {
      throw new Error("permitId must not be blank");
    }
    const idempotencyKey =
      typeof options?.idempotencyKey === "string"
        ? options.idempotencyKey.trim()
        : "";
    if (!idempotencyKey) {
      throw new Error("idempotencyKey must not be blank");
    }
    // Count code points, as the server does, not UTF-16 code units.
    const keyLength = idempotencyKey.replace(
      /[\uD800-\uDBFF][\uDC00-\uDFFF]/g,
      "_"
    ).length;
    if (keyLength > MAX_IDEMPOTENCY_KEY_LENGTH) {
      throw new Error(
        `idempotencyKey must be at most ${MAX_IDEMPOTENCY_KEY_LENGTH} characters`
      );
    }
    const response: AxiosResponse = await this.client.post(
      "/v1/awi/execute",
      {
        session_id: sessionId,
        action,
        parameters: parameters || {},
        representation_request: options.representation,
        dry_run: options.dryRun ?? false,
      },
      {
        headers: {
          "X-Permit-Id": permitId,
          "Idempotency-Key": idempotencyKey,
        },
      }
    );
    return response.data;
  }

  async getRepresentation(
    sessionId: string,
    representationType: AWIRepresentationType,
    options?: Record<string, unknown>
  ): Promise<AWIRepresentation> {
    const response: AxiosResponse = await this.client.post("/v1/awi/represent", {
      session_id: sessionId,
      representation_type: representationType,
      options: options || {},
    });
    return response.data;
  }

  async pause(sessionId: string, reason?: string): Promise<unknown> {
    const response: AxiosResponse = await this.client.post("/v1/awi/intervene", {
      session_id: sessionId,
      action: "pause",
      reason,
    });
    return response.data;
  }

  async resume(sessionId: string): Promise<unknown> {
    const response: AxiosResponse = await this.client.post("/v1/awi/intervene", {
      session_id: sessionId,
      action: "resume",
    });
    return response.data;
  }

  async steer(
    sessionId: string,
    instructions: string
  ): Promise<unknown> {
    const response: AxiosResponse = await this.client.post("/v1/awi/intervene", {
      session_id: sessionId,
      action: "steer",
      steer_instructions: instructions,
    });
    return response.data;
  }

  async getSession(sessionId: string): Promise<AWISession> {
    const response: AxiosResponse = await this.client.get(
      `/v1/awi/sessions/${sessionId}`
    );
    return response.data;
  }

  async destroySession(sessionId: string): Promise<void> {
    await this.client.delete(`/v1/awi/sessions/${sessionId}`);
  }

  async createTask(
    taskType: string,
    targetUrl: string,
    actionSequence: Array<Record<string, unknown>>,
    priority?: number
  ): Promise<unknown> {
    const response: AxiosResponse = await this.client.post("/v1/awi/tasks", {
      task_type: taskType,
      target_url: targetUrl,
      action_sequence: actionSequence,
      priority: priority || 5,
    });
    return response.data;
  }

  async getTaskStatus(taskId: string): Promise<unknown> {
    const response: AxiosResponse = await this.client.get(
      `/v1/awi/tasks/${taskId}`
    );
    return response.data;
  }

  async getQueueStatus(): Promise<unknown> {
    const response: AxiosResponse = await this.client.get(
      "/v1/awi/queue/status"
    );
    return response.data;
  }
}

export default AWIClient;
