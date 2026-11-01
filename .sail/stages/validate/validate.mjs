// Validates the branch in the workspace and prints the Validation: what is uncommitted, and how the repository's gate
// ended. The gate is `.sail/lib/gate.sh`, taken from beside $SAIL_CONFIG: the run's own, never the pull request's
// editable workspace copy. Its output goes to stderr as it comes, so the call's log fills while it runs. A gate that
// outlasts GATE_SECONDS is stopped and fails the validation. A failed gate runs again on the branch's merge-base with
// the base: failing there too sets baseRed, which ends the run instead of another pass, since no change of the branch
// fixes it.
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

const root = process.cwd();
const lib = join(dirname(process.env.SAIL_CONFIG), 'lib');
const BASE = 'origin/staging';
const GATE_SECONDS = Number(process.env.SAIL_GATE_SECONDS ?? 1500);
const tail = (text, lines = 80) => text.split('\n').slice(-lines).join('\n').slice(-8000);

const status = spawnSync('git', ['-c', 'core.quotePath=false', 'status', '--porcelain=v1', '--untracked-files=all'], {
  cwd: root,
  encoding: 'utf8',
});
if (status.status !== 0) throw new Error(`git status: ${status.stderr.trim()}`);
const uncommitted = status.stdout
  .split('\n')
  .filter(Boolean)
  .map((line) => line.slice(3));

/** Runs `script` from the run's lib in `cwd`: its exit code and output. It leads a process group, so a stop reaches its workers. */
function run(script, cwd) {
  return new Promise((resolve) => {
    const child = spawn('bash', [join(lib, script)], { cwd, stdio: ['ignore', 'pipe', 'pipe'], detached: true });
    let output = '';
    let timedOut = false;
    const collect = (chunk) => {
      output += chunk;
      process.stderr.write(chunk);
    };
    child.stdout.on('data', collect);
    child.stderr.on('data', collect);
    const timer = setTimeout(() => {
      timedOut = true;
      try {
        process.kill(-child.pid, 'SIGKILL');
      } catch {}
    }, GATE_SECONDS * 1000);
    child.on('close', (code) => {
      clearTimeout(timer);
      if (timedOut) output += `\ngate stopped after ${GATE_SECONDS}s\n`;
      resolve({ exitCode: timedOut ? 124 : (code ?? 1), output });
    });
  });
}

/** Whether the gate fails on the branch's merge-base with the base too, in a worktree of its own. */
async function baseFails() {
  const found = spawnSync('git', ['merge-base', 'HEAD', BASE], { cwd: root, encoding: 'utf8' });
  if (found.status !== 0) return false;
  const dir = join(mkdtempSync(join(tmpdir(), 'sail-validate-base-')), 'base');
  const added = spawnSync('git', ['worktree', 'add', '--detach', dir, found.stdout.trim()], { cwd: root });
  if (added.status !== 0) return false;
  try {
    process.stderr.write(`validate: running the gate on the base, ${found.stdout.trim().slice(0, 12)}\n`);
    const installed = await run('setup.sh', dir);
    if (installed.exitCode !== 0) return false;
    return (await run('gate.sh', dir)).exitCode !== 0;
  } finally {
    spawnSync('git', ['worktree', 'remove', '--force', dir], { cwd: root });
    rmSync(dirname(dir), { recursive: true, force: true });
  }
}

const gate = await run('gate.sh', root);
const verified = gate.exitCode === 0;
const baseRed = verified ? false : await baseFails();
const ok = verified && uncommitted.length === 0;
console.log(
  JSON.stringify({
    ok,
    uncommitted,
    verify: { ok: verified, exitCode: gate.exitCode, tail: tail(gate.output) },
    ...(baseRed ? { baseRed } : {}),
  }),
);
process.exit(ok ? 0 : 1);
