/**
 * AWI TypeScript SDK — Phase 8
 * TypeScript client for Agentic Web Interface (AWI) services
 *
 * Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"
 */

import axios, { AxiosInstance, AxiosResponse } from "axios";

export interface AWIConfig {
  baseUrl: string;
  apiKey: string;
  walletId?: string;
  timeout?: number;
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
 * const result = await client.execute(session.session_id, "search_and_sort", {
 *   query: "laptops",
 *   sort_by: "price"
 * });
 * ```
 */
export class AWIClient {
  private client: AxiosInstance;
  private config: AWIConfig;

  constructor(config: AWIConfig) {
    this.config = config;
    this.client = axios.create({
      baseURL: config.baseUrl,
      timeout: config.timeout || 30000,
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": config.apiKey,
      },
    });
  }

  async discover(): Promise<unknown> {
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
      max_steps: options?.maxSteps || 100,
      allow_human_pause: options?.allowHumanPause ?? true,
      wallet_id: this.config.walletId,
    });
    return response.data;
  }

  async execute(
    sessionId: string,
    action: AWIAction,
    parameters?: Record<string, unknown>,
    options?: {
      representation?: AWIRepresentationType;
      dryRun?: boolean;
    }
  ): Promise<AWIExecutionResult> {
    const response: AxiosResponse = await this.client.post("/v1/awi/execute", {
      session_id: sessionId,
      action,
      parameters: parameters || {},
      representation_request: options?.representation,
      dry_run: options?.dryRun ?? false,
    });
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
