#!/usr/bin/env node
/**
 * TaskFlow reference acceptance runner (Node 20+).
 *
 * Why this file exists — three traps from the 2026-10-29 run:
 *   1. `npm run start:api` spawns npm -> node. Killing the npm shell leaves node
 *      listening, so the NEXT run's health check hits the PREVIOUS build and
 *      silently reports a false 43/43. Fix: free port, unique DB, kill the tree.
 *   2. `vitest` prints "Test Files 2 passed" before "Tests 27 passed"; a naive
 *      /(\d+) passed/ grabs "2" and marks the suite as 2 tests.
 *   3. Comment/activity payloads differ by implementation (`body` vs `content`,
 *      `activity` vs `activities`); check both instead of failing the product.
 *
 * Usage:
 *   node harness/webapp_accept.mjs --dir eval/qoder --out eval/results/qoder.json
 *   node harness/webapp_accept.mjs --dir . --start "npm run start:api" --health /api/health
 *
 * The HTTP checks encode `templates/.../SPEC.md` TaskFlow v1.0. Copy this file
 * as a starting point for another full-stack task, then edit the checks.
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

const IS_WIN = process.platform === 'win32';

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    if (!argv[i].startsWith('--')) continue;
    const key = argv[i].slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) { out[key] = next; i++; } else { out[key] = true; }
  }
  return out;
}

async function freePort() {
  const srv = net.createServer();
  await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve));
  const port = srv.address().port;
  await new Promise((resolve) => srv.close(resolve));
  return port;
}

function killPort(port) {
  if (IS_WIN) {
    spawnSync('powershell', ['-NoProfile', '-Command',
      `Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }`],
      { encoding: 'utf8', timeout: 20000 });
  } else {
    spawnSync('sh', ['-c', `lsof -ti tcp:${port} 2>/dev/null | xargs -r kill -9 2>/dev/null`], { timeout: 20000 });
  }
}

function killTree(child) {
  if (!child || child.pid == null) return;
  if (IS_WIN) {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { timeout: 15000 });
  } else {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { try { child.kill('SIGKILL'); } catch {} }
  }
}

const args = parseArgs(process.argv.slice(2));
const dir = path.resolve(args.dir || '.');
const outJson = path.resolve(args.out || 'accept.json');
const startCmd = String(args.start || 'npm run start:api');
const healthPath = String(args.health || '/api/health');

const results = [];
const logs = [];

function rec(id, title, ok, detail = '') {
  results.push({ id, title, ok: !!ok, detail: String(detail).slice(0, 1200) });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${id} ${title}${detail ? ' :: ' + String(detail).slice(0, 300) : ''}`);
}

function sh(cmd, cmdArgs, opts = {}) {
  const r = spawnSync(cmd, cmdArgs, {
    cwd: dir,
    shell: IS_WIN,
    encoding: 'utf8',
    timeout: opts.timeout || 600000,
    env: { ...process.env, CI: '1', ...(opts.env || {}) },
  });
  const out = `${r.stdout || ''}${r.stderr || ''}`;
  logs.push(`$ ${cmd} ${cmdArgs.join(' ')}\n${out}`.slice(0, 20000));
  return { code: r.status, out };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(base, method, url, body, token) {
  const res = await fetch(base + url, {
    method,
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { status: res.status, data };
}

async function main() {
  const port = Number(args.port || await freePort());
  const base = `http://127.0.0.1:${port}`;
  const dbFile = path.join(dir, `accept-${Date.now()}.db`);

  // --- static checks -------------------------------------------------------
  for (const f of ['package.json', 'README.md', '.env.example', 'Dockerfile', 'docker-compose.yml',
    'web/package.json', 'web/index.html', 'server/package.json']) {
    rec(`file:${f}`, `存在 ${f}`, fs.existsSync(path.join(dir, f)));
  }

  let pkg = {};
  try { pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')); } catch {}
  const scripts = pkg.scripts || {};
  for (const s of ['build', 'test', 'dev', 'start:api']) {
    rec(`script:${s}`, `根脚本 ${s}`, !!scripts[s], scripts[s] || 'missing');
  }
  rec('workspaces', 'npm workspaces 配置', Array.isArray(pkg.workspaces) && pkg.workspaces.length >= 2, JSON.stringify(pkg.workspaces));

  const tsconfig = path.join(dir, 'web/tsconfig.json');
  if (fs.existsSync(tsconfig)) {
    rec('ts-strict', '前端 TS strict', /"strict"\s*:\s*true/.test(fs.readFileSync(tsconfig, 'utf8')));
  } else {
    rec('ts-strict', '存在 web/tsconfig.json', false);
  }

  // --- install / build / test ---------------------------------------------
  let r = sh('npm', ['install', '--no-audit', '--no-fund'], { timeout: 900000 });
  rec('install', 'npm install 成功', r.code === 0, r.out.slice(-1500));

  r = sh('npm', ['run', 'build'], { timeout: 600000 });
  rec('build', 'npm run build 成功', r.code === 0, r.out.slice(-2000));
  rec('build:dist', '生成 web/dist/index.html', fs.existsSync(path.join(dir, 'web/dist/index.html')));

  r = sh('npm', ['test', '--', '--run'], { timeout: 600000 });
  if (r.code !== 0) r = sh('npm', ['test'], { timeout: 600000 });
  const testOut = r.out;
  const passNum = (testOut.match(/Tests\s+(\d+)\s+passed/i) || testOut.match(/(\d+)\s+passed/i) || [])[1];
  const failNum = (testOut.match(/Tests\s+(\d+)\s+failed/i) || testOut.match(/(\d+)\s+failed/i) || [])[1];
  rec('test', 'npm test 全绿', r.code === 0, `exit=${r.code} passed=${passNum ?? '?'} failed=${failNum ?? '?'}\n${testOut.slice(-1200)}`);
  rec('test:count', '测试用例 >= 12', Number(passNum || 0) >= 12, `passed=${passNum || 0}`);

  // --- boot API on a clean, unique port -----------------------------------
  killPort(port); // a previous run may have left node behind
  const child = spawn(startCmd, {
    cwd: dir,
    shell: true,
    detached: !IS_WIN,
    env: { ...process.env, PORT: String(port), DB_FILE: dbFile, NODE_ENV: 'test' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let srvOut = '';
  child.stdout.on('data', (d) => (srvOut += d));
  child.stderr.on('data', (d) => (srvOut += d));

  let up = false;
  for (let i = 0; i < 90; i++) {
    await sleep(1000);
    if (child.exitCode !== null) break;
    try {
      const health = await fetch(base + healthPath);
      if (health.ok) { up = true; break; }
    } catch {}
  }
  rec('server', `API 在 ${port} 启动且 ${healthPath} 可用`, up, srvOut.slice(-1500));
  if (!up) { finish(child, port, dbFile); return; }

  const uniq = Date.now().toString(36).slice(-6);
  const domain = 'taskflow.dev';
  const adminEmail = `admin${uniq}` + '@' + domain;
  const memberEmail = `member${uniq}` + '@' + domain;
  const seedEmail = ['admin', domain].join('@');

  // R1 auth
  let res = await request(base, 'POST', '/api/auth/register', { name: 'Admin', email: adminEmail, password: 'Admin123!' });
  const adminToken = res.data?.token;
  rec('r1:register', '注册返回 201 + token', res.status === 201 && !!adminToken, `${res.status} ${JSON.stringify(res.data).slice(0, 300)}`);

  res = await request(base, 'POST', '/api/auth/register', { name: '', email: 'bad', password: '123' });
  rec('r1:validate', '非法注册返回 400', res.status === 400, `${res.status} ${JSON.stringify(res.data).slice(0, 200)}`);

  res = await request(base, 'POST', '/api/auth/register', { name: 'Member', email: memberEmail, password: 'Member123!' });
  const memberToken = res.data?.token;
  rec('r1:register2', '第二个用户注册成功', res.status === 201 && !!memberToken, res.status);

  res = await request(base, 'POST', '/api/auth/login', { email: adminEmail, password: 'Admin123!' });
  rec('r1:login', '登录返回 200 + token', res.status === 200 && !!res.data?.token, res.status);

  res = await request(base, 'POST', '/api/auth/login', { email: adminEmail, password: 'wrong' });
  rec('r1:login-bad', '错误密码返回 401', res.status === 401, res.status);

  res = await request(base, 'GET', '/api/auth/me', undefined, adminToken);
  rec('r1:me', '/me 返回当前用户', res.status === 200 && (res.data?.email === adminEmail || res.data?.user?.email === adminEmail), `${res.status} ${JSON.stringify(res.data).slice(0, 200)}`);

  res = await request(base, 'GET', '/api/projects', undefined, 'not-a-token');
  rec('r1:401', '无效 token 返回 401', res.status === 401, res.status);

  // R2 RBAC: the seeded admin from SPEC R11 is the reliable admin principal.
  let seedToken = null;
  res = await request(base, 'POST', '/api/auth/login', { email: seedEmail, password: 'Admin123!' });
  if (res.status === 200) seedToken = res.data?.token;
  const sysAdmin = seedToken || adminToken;
  rec('r2:seed-admin', '种子 admin 账号可登录', !!seedToken, `${res.status}`);

  res = await request(base, 'GET', '/api/users', undefined, memberToken);
  rec('r2:403', 'member 访问 /users 返回 403', res.status === 403, res.status);
  res = await request(base, 'GET', '/api/users', undefined, sysAdmin);
  rec('r2:admin', 'admin 访问 /users 返回 200', res.status === 200, res.status);

  // R3 projects
  res = await request(base, 'POST', '/api/projects', { name: 'Apollo', description: 'launch' }, sysAdmin);
  const project = res.data?.project || res.data;
  const pid = project?.id;
  rec('r3:create', '创建项目返回 201 + id', res.status === 201 && !!pid, `${res.status} ${JSON.stringify(res.data).slice(0, 200)}`);

  res = await request(base, 'GET', '/api/projects', undefined, memberToken);
  const list = res.data?.projects || res.data || [];
  rec('r3:isolation', 'member 看不到未加入的项目', Array.isArray(list) && !list.some((p) => p.id === pid), JSON.stringify(list).slice(0, 200));

  res = await request(base, 'POST', `/api/projects/${pid}/members`, { email: memberEmail }, sysAdmin);
  rec('r3:invite', '邀请成员成功', res.status === 200 || res.status === 201, res.status);

  // R4 columns
  res = await request(base, 'GET', `/api/projects/${pid}`, undefined, sysAdmin);
  const cols = res.data?.columns || res.data?.project?.columns || [];
  rec('r4:default-columns', '默认三列 Backlog/In Progress/Done', Array.isArray(cols) && cols.length >= 3, JSON.stringify(cols).slice(0, 300));
  const colId = cols[0]?.id;
  const colDone = cols.find((c) => /done/i.test(c.name || ''))?.id || cols[2]?.id;

  // R5 tasks
  res = await request(base, 'POST', `/api/projects/${pid}/tasks`, { title: 'Design API', priority: 'high', description: 'openapi', columnId: colId }, sysAdmin);
  const task = res.data?.task || res.data;
  const tid = task?.id;
  rec('r5:create', '创建任务返回 201 + id', res.status === 201 && !!tid, `${res.status} ${JSON.stringify(res.data).slice(0, 200)}`);

  res = await request(base, 'PATCH', `/api/tasks/${tid}`, { columnId: colDone, order: 0 }, sysAdmin);
  rec('r5:move', '任务跨列移动成功', res.status === 200 && (res.data?.task?.columnId === colDone || res.data?.columnId === colDone), `${res.status} ${JSON.stringify(res.data).slice(0, 200)}`);

  res = await request(base, 'GET', `/api/projects/${pid}/tasks?q=Design&priority=high`, undefined, sysAdmin);
  const tasks = res.data?.tasks || res.data || [];
  rec('r5:filter', 'q+priority 组合筛选命中', Array.isArray(tasks) && tasks.some((t) => t.id === tid), JSON.stringify(tasks).slice(0, 200));

  res = await request(base, 'POST', `/api/projects/${pid}/tasks`, { title: 'Bad assignee', priority: 'low', assigneeId: 999999 }, sysAdmin);
  rec('r5:assignee-validate', '非成员指派返回 400', res.status === 400, res.status);

  // R6 comments (body/content are both common)
  res = await request(base, 'POST', `/api/tasks/${tid}/comments`, { body: 'looks good' }, memberToken);
  if (res.status === 400) res = await request(base, 'POST', `/api/tasks/${tid}/comments`, { content: 'looks good' }, memberToken);
  const cid = res.data?.comment?.id || res.data?.id || res.data?.commentId;
  rec('r6:comment', '成员可评论', (res.status === 200 || res.status === 201) && !!cid, `${res.status} ${JSON.stringify(res.data).slice(0, 200)}`);
  res = await request(base, 'DELETE', `/api/comments/${cid}`, undefined, sysAdmin);
  rec('r6:comment-delete', 'admin 可删评论', res.status === 200 || res.status === 204, res.status);

  // R7 activity
  res = await request(base, 'GET', `/api/tasks/${tid}/activity`, undefined, sysAdmin);
  const acts = res.data?.activity || res.data?.activities || res.data || [];
  rec('r7:activity', '动态记录 >=2 条', Array.isArray(acts) && acts.length >= 2, JSON.stringify(acts).slice(0, 300));

  // R8 stats
  res = await request(base, 'GET', '/api/dashboard/stats', undefined, sysAdmin);
  const st = res.data?.stats || res.data;
  rec('r8:stats', '统计返回 total/byStatus/byPriority/overdue', res.status === 200 && st && Number.isFinite(st.total) && st.byStatus && st.byPriority && Number.isFinite(st.overdue), JSON.stringify(res.data).slice(0, 400));

  // R11 seed / DB
  rec('r11:db', '启动后生成 SQLite 文件', fs.existsSync(dbFile) && fs.statSync(dbFile).size > 0);

  finish(child, port, dbFile);
}

function finish(child, port, dbFile) {
  killTree(child);
  setTimeout(() => killTree(child), 1500);
  // 只删本轮自己的 DB；按 accept-*.db 通配会误删并行运行的另一个任务。
  for (const suffix of ['', '-wal', '-shm']) {
    if (!dbFile) break;
    const f = dbFile + suffix;
    try { if (fs.existsSync(f)) fs.unlinkSync(f); } catch {}
  }

  const passed = results.filter((r) => r.ok).length;
  const payload = {
    dir, port, at: new Date().toISOString(),
    passed, total: results.length, pct: Math.round((passed / results.length) * 100),
    results, tails: logs.slice(-6),
  };
  fs.writeFileSync(outJson, JSON.stringify(payload, null, 2));
  console.log(`\nSCORE ${passed}/${results.length} (${payload.pct}%) -> ${outJson}`);

  // 验收失败必须让 CI / 调用方看见；此前无论多少 FAIL 都 exit 0，会出现假绿。
  const exitCode = results.length > 0 && passed === results.length ? 0 : 1;
  process.exitCode = exitCode;
  setTimeout(() => process.exit(exitCode), 1500);
}

main().catch((err) => {
  console.error('FATAL', err);
  rec('fatal', 'acceptance crashed', false, err.message);
  finish(null, 0, '');
});
