// The permission profiles every agent stage of this .sail/ runs under, so a command the agents reach for is allowed
// once, here, and not stage by stage. What guards a run is the worktree it works in, the write globs, the engine's deny
// set, and the outward actions (push, pull request, merge, ticket moves) living in script stages: so a stage may run any
// command, and `deny` names only what reaches out of the run or, for a reader, changes the branch. This file is identical
// in the three Yasli repositories, so the paths below span all three.
import type { Permissions } from 'sail';

/** What no agent runs: anything that reaches outside the run, a deployed service, or another process on the machine. */
const OUTWARD = [
  'git push *',
  'git remote *',
  'git worktree *',
  'git config *',
  'gh *',
  'curl *',
  'wget *',
  'ssh *',
  'scp *',
  'rsync *',
  'nc *',
  'npm publish *',
  'npm login *',
  'npm adduser *',
  'npx wrangler *',
  'wrangler *',
  'railway *',
  'aws *',
  'uv publish *',
  'bun publish *',
  'sail *',
  'security *',
  'open *',
  'osascript *',
  'kill *',
  'pkill *',
  'killall *',
];

/** What changes the branch, the installed dependencies or the working tree: never a reader's to run. */
const CHANGES = [
  'git add *',
  'git commit *',
  'git rm *',
  'git mv *',
  'git restore *',
  'git stash *',
  'git reset *',
  'git rebase *',
  'git merge *',
  'git cherry-pick *',
  'git revert *',
  'git am *',
  'git apply *',
  'git tag *',
  'npm install *',
  'npm ci *',
  'npm uninstall *',
  'npm update *',
  'uv add *',
  'uv remove *',
  'uv sync *',
  'uv lock *',
  'uv pip *',
  'ruff format *',
  'rm *',
  'mv *',
  'sed -i*',
];

/** The repositories' own paths, which a stage that changes the branch writes. */
const REPOSITORY = [
  'src/**',
  'tests/**',
  'scripts/**',
  'schemas/**',
  'migrations/**',
  'data/**',
  'public/**',
  'docs/**',
  '.sail/**',
  'package.json',
  'package-lock.json',
  'pyproject.toml',
  'uv.lock',
  'tsconfig.json',
  'eslint.config.js',
  'vitest.config.ts',
  'astro.config.mjs',
  'README.md',
  'CLAUDE.md',
];

/**
 * A stage that reads the change and writes only its own files: it runs tests and any read it needs, and never commits,
 * moves files, installs or rewrites the branch.
 */
export const readonly: Permissions = {
  read: ['**'],
  write: ['$STAGE_OUT/**'],
  commands: ['*'],
  deny: [...OUTWARD, ...CHANGES],
};

/** The demonstrate stage: a reader that may also call the services `.sail/lib/demo.sh` starts on localhost. */
export const demonstrator: Permissions = {
  ...readonly,
  deny: (readonly.deny ?? []).filter((command) => command !== 'curl *'),
};

/**
 * A stage that changes the branch: it writes the repository's own paths, commits, adds a dependency and runs anything
 * else, but never pushes or reaches outside the run. Files go with `git rm` and
 * `git mv`, so a removal is always in a commit.
 */
export const builder: Permissions = {
  read: ['**'],
  write: [...REPOSITORY, '$STAGE_OUT/**'],
  commands: ['*'],
  deny: [...OUTWARD, 'rm *'],
};

/** `profile` with `tools` added, such as WebFetch for a stage that reads an outside API's docs. */
export function withTools(profile: Permissions, tools: readonly string[]): Permissions {
  return { ...profile, tools: [...(profile.tools ?? []), ...tools] };
}
