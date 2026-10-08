/** Typed errors for the gateway client. Mirrors b2a_sdk/errors.py. */

export type JsonObject = Record<string, unknown>;

export class AgentMiddlewareError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "AgentMiddlewareError";
  }
}

/** The API returned an error or a response the client cannot parse. */
export class APIError extends AgentMiddlewareError {
  readonly statusCode: number | null;
  readonly payload: JsonObject;

  constructor(message: string, statusCode: number | null = null, payload: JsonObject = {}) {
    super(message);
    this.name = "APIError";
    this.statusCode = statusCode;
    this.payload = payload;
  }
}

/** The request could not be completed at the HTTP transport boundary. */
export class TransportError extends AgentMiddlewareError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "TransportError";
  }
}

/** The supplied API key was missing or invalid. */
export class AuthenticationError extends APIError {
  constructor(message: string, statusCode: number | null = 401, payload: JsonObject = {}) {
    super(message, statusCode, payload);
    this.name = "AuthenticationError";
  }
}

/** The authenticated key cannot access the requested resource. */
export class AuthorizationError extends APIError {
  constructor(message: string, statusCode: number | null = 403, payload: JsonObject = {}) {
    super(message, statusCode, payload);
    this.name = "AuthorizationError";
  }
}

/** A governed invocation was denied by its permit. */
export class PermitDeniedError extends AuthorizationError {
  readonly reason: string;
  readonly receiptId: string | null;

  constructor(reason: string, receiptId: string | null = null, payload: JsonObject = {}) {
    super(reason, 403, payload);
    this.name = "PermitDeniedError";
    this.reason = reason;
    this.receiptId = receiptId;
  }
}

/** An idempotency key is in progress or was reused for another request. */
export class IdempotencyConflictError extends APIError {
  constructor(message: string, statusCode: number | null = 409, payload: JsonObject = {}) {
    super(message, statusCode, payload);
    this.name = "IdempotencyConflictError";
  }
}

/** The upstream dispatch occurred, but its outcome cannot be confirmed. */
export class DeliveryUncertainError extends APIError {
  readonly receiptId: string;

  constructor(receiptId: string, message = "delivery_uncertain", payload: JsonObject = {}) {
    super(message, 504, payload);
    this.name = "DeliveryUncertainError";
    this.receiptId = receiptId;
  }
}

/** The wallet does not have enough credits for an operation. */
export class InsufficientFundsError extends APIError {
  readonly walletId: string;
  readonly shortfall: number | null;
  readonly topUpUrl: string | null;
  readonly receiptId: string | null;

  constructor(
    walletId: string,
    opts: { shortfall?: unknown; topUpUrl?: unknown; receiptId?: string | null; payload?: JsonObject } = {},
  ) {
    const shortfall =
      opts.shortfall === null || opts.shortfall === undefined || opts.shortfall === "unknown"
        ? null
        : Number(opts.shortfall);
    const topUpUrl = typeof opts.topUpUrl === "string" ? opts.topUpUrl : null;
    let message = `Insufficient funds in wallet ${walletId}. Shortfall: ${
      Number.isNaN(shortfall) ? "unknown" : String(shortfall)
    } credits.`;
    if (topUpUrl) message += ` Top up at: ${topUpUrl}`;
    super(message, 402, opts.payload ?? {});
    this.name = "InsufficientFundsError";
    this.walletId = walletId;
    this.shortfall = typeof shortfall === "number" && !Number.isNaN(shortfall) ? shortfall : null;
    this.topUpUrl = topUpUrl;
    this.receiptId = opts.receiptId ?? null;
  }
}
