/**
 * Typed value objects for the gateway permit, call and receipt surface.
 * Shapes and validation mirror b2a_sdk/models.py. Credit amounts stay
 * strings on the wire so no precision is lost in transit.
 */
import type { JsonObject } from "./errors.js";

export type { JsonObject };

function requiredString(data: JsonObject, key: string): string {
  const value = data[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`response field '${key}' must be a non-empty string`);
  }
  return value;
}

function optionalString(data: JsonObject, key: string): string | null {
  const value = data[key];
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") {
    throw new Error(`response field '${key}' must be a string or null`);
  }
  return value;
}

function stringList(data: JsonObject, key: string): string[] {
  const value = data[key];
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error(`response field '${key}' must be a string list`);
  }
  return [...value];
}

function decimalString(data: JsonObject, key: string): string {
  const value = data[key];
  if (typeof value !== "string" && typeof value !== "number") {
    throw new Error(`response field '${key}' must be a decimal`);
  }
  const text = String(value);
  if (text.trim() === "" || !Number.isFinite(Number(text))) {
    throw new Error(`response field '${key}' must be a decimal`);
  }
  return text;
}

function dateString(data: JsonObject, key: string): string {
  const value = requiredString(data, key);
  if (Number.isNaN(Date.parse(value))) {
    throw new Error(`response field '${key}' must be an ISO-8601 string`);
  }
  return value;
}

/** One executable tool advertised by MCP discovery. */
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: JsonObject;
  annotations: JsonObject;
  raw: JsonObject;
}

export function parseToolDefinition(data: unknown): ToolDefinition {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("tool definition must be an object");
  }
  const obj = data as JsonObject;
  const inputSchema = obj.inputSchema ?? {};
  const annotations = obj.annotations ?? {};
  if (!inputSchema || typeof inputSchema !== "object" || Array.isArray(inputSchema)) {
    throw new Error("response field 'inputSchema' must be an object");
  }
  if (!annotations || typeof annotations !== "object" || Array.isArray(annotations)) {
    throw new Error("response field 'annotations' must be an object");
  }
  const description = obj.description;
  return {
    name: requiredString(obj, "name"),
    description: typeof description === "string" ? description : "",
    inputSchema: { ...(inputSchema as JsonObject) },
    annotations: { ...(annotations as JsonObject) },
    raw: { ...obj },
  };
}

/** Input for creating a signed, scoped permit. */
export interface PermitRequestInput {
  issuerWalletId: string;
  subjectWalletId: string;
  maxCredits: string;
  expiresAt: string;
  subjectKeyId?: string | null;
  scopes?: string[];
  allowedTools?: string[];
  nonce?: string;
}

export function permitRequestToPayload(input: PermitRequestInput): JsonObject {
  const payload: JsonObject = {
    issuer_wallet_id: input.issuerWalletId,
    subject_wallet_id: input.subjectWalletId,
    subject_key_id: input.subjectKeyId ?? null,
    scopes: [...(input.scopes ?? [])],
    allowed_tools: [...(input.allowedTools ?? [])],
    max_credits: input.maxCredits,
    expires_at: input.expiresAt,
  };
  if (input.nonce !== undefined) payload.nonce = input.nonce;
  return payload;
}

/** A signed authorization permit returned by the gateway. */
export interface Permit {
  permitId: string;
  issuerWalletId: string;
  subjectWalletId: string;
  subjectKeyId: string | null;
  scopes: string[];
  allowedTools: string[];
  maxCredits: string;
  spentCredits: string;
  expiresAt: string;
  nonce: string;
  status: string;
  signature: string;
  keyId: string;
  issuedAt: string;
  revokedAt: string | null;
  raw: JsonObject;
}

export function parsePermit(data: unknown): Permit {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("permit must be an object");
  }
  const obj = data as JsonObject;
  return {
    permitId: requiredString(obj, "permit_id"),
    issuerWalletId: requiredString(obj, "issuer_wallet_id"),
    subjectWalletId: requiredString(obj, "subject_wallet_id"),
    subjectKeyId: optionalString(obj, "subject_key_id"),
    scopes: stringList(obj, "scopes"),
    allowedTools: stringList(obj, "allowed_tools"),
    maxCredits: decimalString(obj, "max_credits"),
    spentCredits: decimalString(obj, "spent_credits"),
    expiresAt: dateString(obj, "expires_at"),
    nonce: requiredString(obj, "nonce"),
    status: requiredString(obj, "status"),
    signature: requiredString(obj, "signature"),
    keyId: requiredString(obj, "key_id"),
    issuedAt: dateString(obj, "issued_at"),
    revokedAt: obj.revoked_at === null || obj.revoked_at === undefined ? null : dateString(obj, "revoked_at"),
    raw: { ...obj },
  };
}

/** A signed receipt for a governed invocation outcome. */
export interface Receipt {
  receiptId: string;
  idempotencyRecordId: string | null;
  permitId: string;
  walletId: string;
  keyId: string | null;
  tool: string;
  requestHash: string;
  responseHash: string | null;
  ledgerEntryId: string | null;
  dispatchAttemptId: string | null;
  creditsAuthorized: string;
  creditsCharged: string;
  outcome: string;
  auditEventId: string | null;
  createdAt: string;
  signature: string;
  signatureKeyId: string;
  raw: JsonObject;
}

export function parseReceipt(data: unknown): Receipt {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("receipt must be an object");
  }
  const obj = data as JsonObject;
  return {
    receiptId: requiredString(obj, "receipt_id"),
    idempotencyRecordId: optionalString(obj, "idempotency_record_id"),
    permitId: requiredString(obj, "permit_id"),
    walletId: requiredString(obj, "wallet_id"),
    keyId: optionalString(obj, "key_id"),
    tool: requiredString(obj, "tool"),
    requestHash: requiredString(obj, "request_hash"),
    responseHash: optionalString(obj, "response_hash"),
    ledgerEntryId: optionalString(obj, "ledger_entry_id"),
    dispatchAttemptId: optionalString(obj, "dispatch_attempt_id"),
    creditsAuthorized: decimalString(obj, "credits_authorized"),
    creditsCharged: decimalString(obj, "credits_charged"),
    outcome: requiredString(obj, "outcome"),
    auditEventId: optionalString(obj, "audit_event_id"),
    createdAt: dateString(obj, "created_at"),
    signature: requiredString(obj, "signature"),
    signatureKeyId: requiredString(obj, "signature_key_id"),
    raw: { ...obj },
  };
}

/** Successful MCP result plus its signed receipt. */
export interface InvocationResult {
  content: JsonObject[];
  structuredContent: JsonObject | null;
  receipt: Receipt;
  raw: JsonObject;
}

/** Server-side signature verification result. */
export interface ReceiptVerification {
  valid: boolean;
  reason: string | null;
  receipt: Receipt | null;
  raw: JsonObject;
}
