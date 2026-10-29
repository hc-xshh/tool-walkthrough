import test from "node:test";
import assert from "node:assert/strict";
import { runQueue } from "../src/queue.js";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const jobsOf = (n) => Array.from({ length: n }, (_, i) => ({ i }));

test("respects concurrency limit", async () => {
  let active = 0;
  let peak = 0;
  const jobs = jobsOf(9);
  const out = await runQueue(
    jobs,
    async (job) => {
      active += 1;
      peak = Math.max(peak, active);
      await delay(8);
      active -= 1;
      return job.i;
    },
    { concurrency: 3 }
  );
  assert.deepEqual(out, jobs.map((job) => job.i));
  assert.ok(peak <= 3, `peak was ${peak}`);
  assert.ok(peak >= 2, `pool never overlapped: peak ${peak}`);
});

test("concurrency defaults to one", async () => {
  let active = 0;
  let peak = 0;
  await runQueue(jobsOf(4), async () => {
    active += 1;
    peak = Math.max(peak, active);
    await delay(5);
    active -= 1;
  });
  assert.equal(peak, 1);
});

test("results keep input order", async () => {
  const jobs = Array.from({ length: 12 }, (_, i) => ({
    i,
    delay: ((i * 7) % 5) * 3,
  }));
  const out = await runQueue(
    jobs,
    async (job) => {
      await delay(job.delay);
      return job.i;
    },
    { concurrency: 4 }
  );
  assert.deepEqual(out, jobs.map((job) => job.i));
});

test("retryable errors are retried up to three attempts", async () => {
  let attempts = 0;
  const out = await runQueue(
    ["job"],
    async () => {
      attempts += 1;
      if (attempts < 3) {
        throw Object.assign(new Error("busy"), { retryable: true });
      }
      return "done";
    },
    { concurrency: 1 }
  );
  assert.deepEqual(out, ["done"]);
  assert.equal(attempts, 3);
});

test("permanent errors are not retried", async () => {
  let attempts = 0;
  const boom = Object.assign(new Error("bad request"), { status: 400 });
  await assert.rejects(
    runQueue(
      ["job"],
      async () => {
        attempts += 1;
        throw boom;
      },
      { concurrency: 1 }
    ),
    /bad request/
  );
  assert.equal(attempts, 1);
});

test("retry budget is exhausted", async () => {
  let attempts = 0;
  await assert.rejects(
    runQueue(
      ["job"],
      async () => {
        attempts += 1;
        throw Object.assign(new Error("still busy"), { status: 429 });
      },
      { concurrency: 1 }
    ),
    /still busy/
  );
  assert.equal(attempts, 3);
});

test("worker receives index", async () => {
  const seen = [];
  const jobs = [{ id: "a" }, { id: "b" }];
  await runQueue(
    jobs,
    async (job, index) => {
      seen.push([job.id, index]);
      return job.id;
    },
    { concurrency: 1 }
  );
  assert.deepEqual(seen, [
    ["a", 0],
    ["b", 1],
  ]);
});

test("empty input returns empty array", async () => {
  let called = 0;
  const out = await runQueue(
    [],
    async () => {
      called += 1;
    },
    { concurrency: 5 }
  );
  assert.deepEqual(out, []);
  assert.equal(called, 0);
});
