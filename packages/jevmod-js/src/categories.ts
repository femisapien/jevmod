// The questions live in categories.json so every implementation (Python, npm, MCP) asks Jev exactly the
// same thing. The file is a verbatim copy of jevmod/categories.json (see scripts/sync-categories.mjs).
import raw from "./categories.json";

export interface Category {
  readonly label: string;
  /** Question text with a `{m}` placeholder for the message path inside the state. */
  readonly instructions: string;
  readonly criteria: { readonly true: string; readonly false: string };
}

export type CategoryName = keyof typeof raw.categories;

export const CATEGORIES: Readonly<Record<CategoryName, Category>> = raw.categories;

/** Category names in the order they appear in categories.json. */
export const CATEGORY_NAMES: readonly CategoryName[] = Object.keys(raw.categories) as CategoryName[];

export const CATEGORIES_VERSION: number = raw.version;

export function isCategory(name: string): name is CategoryName {
  return Object.prototype.hasOwnProperty.call(raw.categories, name);
}
