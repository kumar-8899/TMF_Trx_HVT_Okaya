import "@testing-library/jest-dom";

// jsdom has no WebSocket; stub it so useStream() doesn't throw in tests.
class FakeWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  close() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).WebSocket = FakeWebSocket;
