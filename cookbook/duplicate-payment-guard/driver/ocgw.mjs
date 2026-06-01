// ocgw.mjs — a minimal raw-WebSocket client for the OpenClaw Gateway
// protocol (v3/v4). The published `openclaw-sdk` is pinned to protocol 1
// and no longer handshakes with current gateways, so we speak the
// protocol directly. This is small and version-current.
//
// Uses the trusted same-process backend path documented in
// docs/gateway/protocol.md: client.id "gateway-client", mode "backend",
// authenticated with the shared gateway token over loopback — no device
// pairing required.

import WebSocket from "ws";

export class Gateway {
  constructor({ url, token }) {
    this.url = url;
    this.token = token;
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
    this.eventHandlers = [];
  }

  onEvent(fn) {
    this.eventHandlers.push(fn);
  }

  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url, { maxPayload: 64 * 1024 * 1024 });
      this.ws = ws;
      let handshakeSent = false;

      const sendConnect = () => {
        handshakeSent = true;
        const id = String(this.nextId++);
        this.pending.set(id, { resolve: resolve, reject, isConnect: true });
        ws.send(JSON.stringify({
          type: "req",
          id,
          method: "connect",
          params: {
            minProtocol: 3,
            maxProtocol: 4,
            client: { id: "gateway-client", version: "0.1.0", platform: "node", mode: "backend" },
            role: "operator",
            scopes: ["operator.read", "operator.write", "operator.approvals", "operator.admin"],
            caps: [],
            commands: [],
            permissions: {},
            auth: { token: this.token },
          },
        }));
      };

      ws.on("open", () => {
        // Some gateways send a connect.challenge event first; others
        // accept the connect req immediately. Send connect on open; if a
        // challenge arrives we have already sent (server tolerates).
        sendConnect();
      });

      ws.on("message", (raw) => {
        let frame;
        try { frame = JSON.parse(raw.toString()); } catch { return; }

        // Pre-connect challenge: (re)send connect if we somehow haven't.
        if (frame.type === "event" && frame.event === "connect.challenge") {
          if (!handshakeSent) sendConnect();
          return;
        }
        if (frame.type === "res") {
          const p = this.pending.get(frame.id);
          if (!p) return;
          this.pending.delete(frame.id);
          if (frame.ok === false || frame.error) {
            p.reject(new Error(frame.error?.message || "rpc error"));
          } else {
            p.resolve(frame.result ?? frame.payload ?? frame);
          }
          return;
        }
        if (frame.type === "event") {
          for (const h of this.eventHandlers) h(frame);
        }
      });

      ws.on("error", (e) => reject(e));
      ws.on("close", () => {
        for (const [, p] of this.pending) p.reject(new Error("connection closed"));
        this.pending.clear();
      });
    });
  }

  request(method, params = {}, timeoutMs = 60000) {
    return new Promise((resolve, reject) => {
      const id = String(this.nextId++);
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timeout: ${method}`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
      this.ws.send(JSON.stringify({ type: "req", id, method, params }));
    });
  }

  close() {
    try { this.ws?.close(); } catch {}
  }
}
