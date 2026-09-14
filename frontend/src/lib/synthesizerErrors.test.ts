import { describe, it, expect, vi, afterEach } from "vitest";
import { createBrowserSynthesizer } from "./browserSynthesizer";
import { createServerSynthesizer } from "./serverSynthesizer";
import type { MainMessage, WorkerMessage } from "./browserTTS/types";

// The engine classifies a null result by asking the synthesizer for its error.
// A block that is skipped after a failed one must therefore read as clean.

class FakeWorker {
  static instance: FakeWorker;
  onmessage: ((e: MessageEvent<WorkerMessage>) => void) | null = null;
  onerror: ((e: ErrorEvent) => void) | null = null;
  sent: MainMessage[] = [];
  constructor() { FakeWorker.instance = this; }
  postMessage(msg: MainMessage) { this.sent.push(msg); }
  terminate() {}
  reply(msg: WorkerMessage) { this.onmessage?.({ data: msg } as MessageEvent<WorkerMessage>); }
}

afterEach(() => vi.unstubAllGlobals());

describe("browser synthesizer", () => {
  it("clears the error when a later block is skipped", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const synth = createBrowserSynthesizer();
    const worker = FakeWorker.instance;

    const failed = synth.synthesize(0, "Real words", "doc", "kokoro-browser", "af_heart");
    const failedId = (worker.sent.at(-1) as { requestId: string }).requestId;
    worker.reply({ type: "error", requestId: failedId, error: "Kernel failed" });
    expect(await failed).toBeNull();
    expect(synth.getError()).toBe("Kernel failed");

    const skipped = synth.synthesize(1, "———", "doc", "kokoro-browser", "af_heart");
    const skippedId = (worker.sent.at(-1) as { requestId: string }).requestId;
    worker.reply({ type: "skipped", requestId: skippedId });
    expect(await skipped).toBeNull();
    expect(synth.getError()).toBeNull();
  });
});

describe("server synthesizer", () => {
  it("clears the error when a later block is skipped", async () => {
    const synth = createServerSynthesizer({
      sendWS: vi.fn(),
      checkWSConnected: () => true,
      fetchAudio: vi.fn(),
    });

    const failed = synth.synthesize(0, "Real words", "doc", "kokoro", "af_heart");
    synth.onWSMessage({
      type: "status", document_id: "doc", block_idx: 0, status: "error",
      error: "worker OOM", recoverable: true, model_slug: "kokoro", voice_slug: "af_heart",
    });
    expect(await failed).toBeNull();
    expect(synth.getError()).toBe("worker OOM");

    const skipped = synth.synthesize(1, "———", "doc", "kokoro", "af_heart");
    synth.onWSMessage({
      type: "status", document_id: "doc", block_idx: 1, status: "skipped",
      model_slug: "kokoro", voice_slug: "af_heart",
    });
    expect(await skipped).toBeNull();
    expect(synth.getError()).toBeNull();
  });
});
