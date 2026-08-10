import { InlineKeyboard } from "grammy";

export interface ConfirmationChoice {
  value: string;
  label: string;
}

/**
 * One button per choice, each on its own row.
 *
 * The action id is embedded in the callback data rather than read from
 * module state, so a button on an older message cannot answer a newer
 * confirmation.
 */
export function buildConfirmationKeyboard(
  actionId: string,
  choices: ConfirmationChoice[],
): InlineKeyboard {
  const kb = new InlineKeyboard();
  choices.forEach((choice, i) => {
    kb.text(choice.label, `confirm:${actionId}:${choice.value}`);
    // Break between buttons only -- a trailing .row() leaves an empty row.
    if (i < choices.length - 1) kb.row();
  });
  return kb;
}
