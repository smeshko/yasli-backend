// validate: everything is committed, and the repository's gate, `.sail/lib/gate.sh`, passes. A gate that fails on the
// branch's merge-base too sets baseRed. Shared: the factory runs it after implement, and review runs it beside its
// reviewers and after each fix.
import { script, z } from 'sail';

export const Validation = z.object({
  ok: z.boolean(),
  /** Paths left uncommitted. */
  uncommitted: z.array(z.string()),
  /** How the gate ended. */
  verify: z.object({
    ok: z.boolean(),
    exitCode: z.number().int(),
    tail: z.string(),
  }),
  /** The gate fails on the base too: staging is red, and no change of the branch fixes it. */
  baseRed: z.boolean().optional(),
});

export const validate = script('validate', {
  run: './run.sh',
  output: Validation,
  // Twice the gate, when it fails: once here, once on the base.
  timeoutSeconds: 3600,
});

/** The end of the gate's output on a red base, for a run's failure reason. */
export function redTests(validation: z.infer<typeof Validation>): string {
  return validation.verify.tail.trim().split('\n').slice(-3).join('; ');
}
