/** Telegram hard-limits callback_data to 64 bytes; our prefixes use 10. */
const SLUG_BUDGET_BYTES = 54;

/**
 * Stable short id for a vault item: the filename stem, truncated to fit
 * Telegram's callback_data limit. The server resolves truncated slugs by
 * prefix match.
 */
export function callbackSlug(item: { name: string; path?: string }): string {
  const stem = item.path
    ? item.path.split("/").pop()!.replace(/\.md$/, "")
    : item.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  let slug = stem;
  while (Buffer.byteLength(slug, "utf8") > SLUG_BUDGET_BYTES) {
    slug = slug.slice(0, -1);
  }
  return slug;
}
