import { describe, expect, it, vi } from "vitest";
import { tool } from "ai";
import { z } from "zod";
import {
  GovernedInvokeError,
  PermitDeniedError,
  governedTool,
  type GovernedTool,
} from "../src/index.js";

const OPTIONS = {
  baseUrl: "https://api.example.test",
  apiKey: "test-key",
  issuerWalletId: "wallet-issuer",
  subjectWalletId: "wallet-subject",
  toolName: "partner.notes.write",
};

function makeBaseTool() {
  return tool({
    description: "Write a note",
    inputSchema: z.object({ text: z.string() }),
    execute: async () => ({ wrote: false }),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function execOptions() {
  return { toolCallId: "call_123", messages: [] as never[] };
}

describe("governedTool", () => {
  it("permit granted runs the tool and records the receipt", async () => {
    const calls: string[] = [];
    const fetchFn = vi.fn(async (url: unknown) => {
      const path = String(url);
      calls.push(path);
      if (path.endsWith("/v1/permits")) {
        return jsonResponse({ permit_id: "permit-1" }, 201);
      }
      if (path.endsWith("/v1/permits/verify")) {
        return jsonResponse({ valid: true, reason: null });
      }
      if (path.endsWith("/mcp/messages")) {
        return jsonResponse({
          result: {
            content: [{ type: "text", text: "note saved" }],
            structuredContent: { saved: true },
            receipt: { receipt_id: "rc-1", outcome: "success" },
          },
        });
      }
      throw new Error(`unexpected call to ${path}`);
    });

    const wrapped = governedTool(makeBaseTool(), {
      ...OPTIONS,
      fetchFn: fetchFn as typeof fetch,
    }) as GovernedTool & {
      execute: (input: unknown, execOptions?: never) => Promise<unknown>;
    };

    const output = await wrapped.execute({ text: "hello" }, execOptions());
    expect(output).toEqual({ saved: true });
    expect(wrapped.lastReceipt).toEqual({ receipt_id: "rc-1", outcome: "success" });
    expect(calls).toEqual([
      "https://api.example.test/v1/permits",
      "https://api.example.test/v1/permits/verify",
      "https://api.example.test/mcp/messages",
    ]);

    const permitBody = JSON.parse(String(fetchFn.mock.calls[0]?.[1]?.body ?? "{}")) as Record<
      string,
      unknown
    >;
    expect(permitBody["allowed_tools"]).toEqual(["partner.notes.write"]);
    const invokeBody = JSON.parse(String(fetchFn.mock.calls[2]?.[1]?.body ?? "{}")) as {
      params: { mcpContext: Record<string, string> };
    };
    expect(invokeBody.params.mcpContext["permit_id"]).toBe("permit-1");
  });

  it("permit denied skips the tool dispatch", async () => {
    const calls: string[] = [];
    const fetchFn = vi.fn(async (url: unknown) => {
      const path = String(url);
      calls.push(path);
      if (path.endsWith("/v1/permits")) {
        return jsonResponse({ permit_id: "permit-2" }, 201);
      }
      if (path.endsWith("/v1/permits/verify")) {
        return jsonResponse({ valid: false, reason: "permit_budget_exceeded" });
      }
      throw new Error(`unexpected call to ${path}`);
    });

    const wrapped = governedTool(makeBaseTool(), {
      ...OPTIONS,
      fetchFn: fetchFn as typeof fetch,
    }) as GovernedTool & {
      execute: (input: unknown, execOptions?: never) => Promise<unknown>;
    };

    await expect(wrapped.execute({ text: "hello" }, execOptions())).rejects.toBeInstanceOf(
      PermitDeniedError,
    );
    expect(calls).not.toContain("https://api.example.test/mcp/messages");
    expect(wrapped.lastReceipt).toBeNull();
  });

  it("a failing tool call still records the failure receipt", async () => {
    const fetchFn = vi.fn(async (url: unknown) => {
      const path = String(url);
      if (path.endsWith("/v1/permits")) {
        return jsonResponse({ permit_id: "permit-3" }, 201);
      }
      if (path.endsWith("/v1/permits/verify")) {
        return jsonResponse({ valid: true, reason: null });
      }
      return jsonResponse({
        result: {
          content: [{ type: "text", text: "tool blew up" }],
          isError: true,
          error: "tool_blew_up",
          receipt: { receipt_id: "rc-3", outcome: "tool_error" },
        },
      });
    });

    const wrapped = governedTool(makeBaseTool(), {
      ...OPTIONS,
      fetchFn: fetchFn as typeof fetch,
    }) as GovernedTool & {
      execute: (input: unknown, execOptions?: never) => Promise<unknown>;
    };

    const err = await wrapped
      .execute({ text: "hello" }, execOptions())
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(GovernedInvokeError);
    expect(wrapped.lastReceipt).toEqual({ receipt_id: "rc-3", outcome: "tool_error" });
  });
});
