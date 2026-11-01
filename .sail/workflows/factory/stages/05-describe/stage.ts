// describe: writes the pull request's title and body from the ticket and the plan, as create-pr does, carrying the
// plan's Demonstration section for the review workflow, and names the follow-up work the run found, which the workflow
// files itself.
import { agent, file, value, z } from 'sail';
import { TicketInput } from 'sail/intakes';
import { readonly } from '../../../../lib/permissions';
import { FollowUp } from '../../../../stages/file-follow-ups/stage';

export const PrDescription = z.object({
  title: z.string().max(120),
  bodyFile: z.string(),
  /** Work outside this branch the run found: each becomes a ticket. */
  followUps: z.array(FollowUp.omit({ fromReview: true })),
});

export const describe = agent('describe', {
  prompt: './prompt.md',
  consumes: { ticket: value(TicketInput), plan: file('plan.md') },
  produces: { 'pr-body.md': 'file' },
  output: PrDescription,
  model: 'fast',
  // validate passed the gate on this HEAD before describe runs, so a test run here only spends minutes and load.
  permissions: {
    ...readonly,
    deny: [...(readonly.deny ?? []), '.sail/lib/gate.sh*', 'npm run test*', 'npm test*', 'uv run pytest*'],
  },
  budget: { maxTurns: 30, maxUsd: 1, maxMinutes: 15 },
  conventions: ['.sail/REPO.md'],
});
