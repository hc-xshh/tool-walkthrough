export async function runQueue(jobs, worker, options = {}) {
  const concurrency = Math.max(1, options.concurrency ?? 1);
  const maxAttempts = options.maxAttempts ?? 3;
  const results = new Array(jobs.length);
  let next = 0;

  async function runOne(index) {
    for (let attempt = 1; ; attempt += 1) {
      try {
        results[index] = await worker(jobs[index], index);
        return;
      } catch (err) {
        const retryable =
          err && (err.retryable === true || err.status === 429);
        if (!retryable || attempt >= maxAttempts) {
          throw err;
        }
      }
    }
  }

  async function lane() {
    while (true) {
      const index = next;
      next += 1;
      if (index >= jobs.length) {
        return;
      }
      await runOne(index);
    }
  }

  const lanes = Math.min(concurrency, jobs.length);
  await Promise.all(Array.from({ length: lanes }, () => lane()));
  return results;
}
