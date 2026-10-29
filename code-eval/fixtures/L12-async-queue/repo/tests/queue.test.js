import test from "node:test";
import assert from "node:assert/strict";
import { runQueue } from "../src/queue.js";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("preserves input order", async () => {
  const jobs = [
    { id: "a", delay: 30 },
    { id: "b", delay: 0 },
    { id: "c", delay: 10 },
  ];
  const out = await runQueue(
    jobs,
    async (job) => {
      await delay(job.delay);
      return job.id;
    },
    { concurrency: 3 }
  );
  assert.deepEqual(out, ["a", "b", "c"]);
});

test("respects concurrency limit", async () => {
  let active = 0;
  let peak = 0;
  const jobs = Array.from({ length: 6 }, (_, i) => i);
  await runQueue(
    jobs,
    async () => {
      active += 1;
      peak = Math.max(peak, active);
      await delay(10);
      active -= 1;
    },
    { concurrency: 2 }
  );
  assert.ok(peak <= 2, `peak was ${peak}`);
});

test("retries retryable errors", async () => {
  let attempts = 0;
  const out = await runQueue(
    [1],
    async () => {
      attempts += 1;
      if (attempts < 3) {
        throw Object.assign(new Error("busy"), { status: 429 });
      }
      return "ok";
    },
    { concurrency: 1 }
  );
  assert.deepEqual(out, ["ok"]);
  assert.equal(attempts, 3);
});
