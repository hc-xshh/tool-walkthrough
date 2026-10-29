// 负例：并发和顺序对了，但把所有错误都当可重试。
export async function runQueue(jobs, worker, options = {}) {
  const concurrency = Math.max(1, options.concurrency ?? 1);
  const results = new Array(jobs.length);
  let next = 0;

  async function runOne(index) {
    let last;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        results[index] = await worker(jobs[index], index);
        return;
      } catch (err) {
        last = err;
      }
    }
    throw last;
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
