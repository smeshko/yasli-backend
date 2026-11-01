// review-conventions: one of review's six reviewers: does the change follow the repository's rules, and is it fit for
// a public repository? It reports findings with a severity and what it checked, and judges nothing: the judge decides
// what each finding becomes.
import { reviewer } from '../../reviewer';

export const reviewConventions = reviewer('review-conventions', 'default');
