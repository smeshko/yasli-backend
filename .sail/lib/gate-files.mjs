// The gate files: what `.sail/lib/gate.sh` and CI read, so a pull request changing one could loosen its own check, plus
// what changes a dependency or a deploy. The list spans the three Yasli repositories, so this file stays identical in each.
export const GATE_FILES = [
  'package.json',
  'package-lock.json',
  'pyproject.toml',
  'uv.lock',
  '.nvmrc',
  'tsconfig.json',
  'eslint.config.js',
  'vitest.config.ts',
  'astro.config.mjs',
  'alembic.ini',
  'Dockerfile',
  'tests/conftest.py',
];
export const GATE_DIRS = ['.github/'];

// The review judges a pull request by the guard its run loaded, so one changing the guard or the merge path would be
// judged by the guard it replaces. So every module the guard and the merge path import, and every script their stages
// run, must be covered too.
export const GUARD_FILES = [
  '.sail/project.yaml',
  '.sail/lib/gate-files.mjs',
  '.sail/lib/gate.sh',
  '.sail/lib/setup.sh',
  '.sail/lib/repo.ts',
  '.sail/lib/permissions.ts',
  '.sail/lib/jev-check.mjs',
  '.sail/lib/duplicates.mjs',
  '.sail/lib/play.sh',
  '.sail/lib/play.mjs',
  '.sail/workflows/review/workflow.ts',
];
// Every file in these folders but a `.md` prompt or template.
export const GUARD_CODE_DIRS = ['.sail/workflows/review/', '.sail/stages/file-follow-ups/', '.sail/stages/validate/'];
export const GUARD_DIRS = [
  '.sail/workflows/review/stages/18-merge/',
  '.sail/workflows/review/stages/21-hand-over/',
  '.sail/workflows/review/stages/22-gate-files/',
];

export function isGateFile(path) {
  return (
    GATE_FILES.includes(path) ||
    GATE_DIRS.some((dir) => path.startsWith(dir)) ||
    GUARD_FILES.includes(path) ||
    GUARD_DIRS.some((dir) => path.startsWith(dir)) ||
    (GUARD_CODE_DIRS.some((dir) => path.startsWith(dir)) && !path.endsWith('.md')) ||
    path.split('/').at(-1) === '.gitignore'
  );
}
