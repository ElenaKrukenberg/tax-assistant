// The hand-written surface over the generated schema types.
// `api.generated.ts` next to this file is what `npm run generate-types` overwrites —
// edit that one and your changes are lost. Add convenience re-exports here instead.

import type { components } from './api.generated';

export type * from './api.generated';

// Convenience exports for common types
export type { components };
export type TaxQuestion = components['schemas']['TaxQuestionRequest'];
export type TaxAnswer = components['schemas']['TaxAnswerResponse'];
export type Source = components['schemas']['SourceResponse'];
export type TraceStep = components['schemas']['TraceStep'];
export type ErrorResponse = components['schemas']['ErrorResponse'];
