// 一个任务队列：并发跑 worker，返回结果。
// 现在的实现把 jobs 一次性全发出去，结果按完成顺序返回，也不重试。
export async function runQueue(jobs, worker, options = {}) {
  const results = [];
  await Promise.all(
    jobs.map(async (job) => {
      results.push(await worker(job));
    })
  );
  return results;
}
