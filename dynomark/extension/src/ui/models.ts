// models.ts -- how a page shows where the user's data goes (design, Security
// Considerations "Cloud model egress": the user can see when page text or
// questions leave the machine). Both models receive it -- the completion
// model every question, the embedding model every query and every page's
// text -- so both are named, each with the daemon's local mark (issue #411).

// --- Types ---

/** A model as status.result reports it. */
export interface ShownModel {
  readonly id: string;
  readonly local: boolean;
}

// --- Pure helpers ---

/** One model with its mark, as an options row shows it. */
export function modelText(model: ShownModel): string {
  return `${model.id} (${model.local ? 'local' : 'cloud'})`;
}

/** The chat surface's line: both models, and a warning when either sends data off this machine. */
export function modelsText(models: { readonly embedding: ShownModel; readonly completion: ShownModel }): string {
  const line = `Answers by ${modelText(models.completion)}; search by ${modelText(models.embedding)}`;
  const leaving = !models.completion.local || !models.embedding.local;
  return leaving ? `${line}. Page text and questions leave this machine.` : line;
}
