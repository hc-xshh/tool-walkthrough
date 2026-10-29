# async-queue

`runQueue(jobs, worker, options)` 按顺序处理一批任务。

约定：

- `jobs`：任务数组；`worker(job, index)` 返回 Promise。
- `options.concurrency`：同时最多跑几个 worker，默认 1。
- 返回：与 `jobs` 等长的结果数组，**顺序与输入一致**。
- `worker` 抛出的错误如果 `retryable === true` 或 `status === 429`，最多尝试 3 次；
  其他错误直接失败。

跑测试：

```bash
npm test
```
