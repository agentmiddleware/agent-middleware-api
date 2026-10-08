# Agent Middleware AWI TypeScript SDK

TypeScript client for the Agentic Web Interface (AWI) lifecycle:
open sessions, execute steps, fetch representations, and pause,
resume, or steer a running session.

The package `@agent-middleware/awi-sdk` is not published to npm
(`"private": true`). Work from a checkout of this repository.

## Installation

Install dependencies and build from this directory:

```bash
npm install
npm run build
```

## Tests

```bash
npm test
```

Tests build first, then run the node test runner against `tests/`
with a stubbed transport, so no gateway is needed.

## Status

Source-only alpha (`0.1.0`, MIT). No registry install path exists;
every command in this file runs from the checkout.
