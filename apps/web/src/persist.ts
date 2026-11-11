import type { CartEntry, Product } from "./types";

/** Saves the cart in this browser so a refresh does not empty it.
 *
 * Only ids, size index, quantity and note are stored. Names and prices are
 * looked up again from the server's catalog when restoring, so a stale or
 * edited value in storage can never change what something costs. */

const KEY = "fm_cart_v1";
const MAX_QTY = 50; // mirrors the server's per-line limit
const MAX_LINES = 40;
const MAX_NOTE = 300;

interface Saved {
  productId: string;
  optionIndex: number;
  qty: number;
  note: string;
}

export function saveCart(cart: Map<string, CartEntry>): void {
  try {
    if (cart.size === 0) {
      localStorage.removeItem(KEY);
      return;
    }
    const rows: Saved[] = Array.from(cart.values()).map((e) => ({
      productId: e.product.id,
      optionIndex: e.optionIndex,
      qty: e.qty,
      note: e.note,
    }));
    localStorage.setItem(KEY, JSON.stringify(rows));
  } catch {
    /* private mode or storage full: the cart just will not survive a refresh */
  }
}

function isSaved(v: unknown): v is Saved {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.productId === "string" &&
    Number.isInteger(r.optionIndex) &&
    Number.isInteger(r.qty) &&
    typeof r.note === "string"
  );
}

/** Rebuild cart entries from storage using the live catalog. Bad rows are dropped. */
export function loadCart(catalog: Product[]): Map<string, CartEntry> {
  const result = new Map<string, CartEntry>();
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return result;
  }
  if (!raw) return result;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return result;
  }
  if (!Array.isArray(parsed)) return result;

  const byId = new Map(catalog.map((p) => [p.id, p]));
  for (const row of parsed.slice(0, MAX_LINES)) {
    if (!isSaved(row)) continue;
    const product = byId.get(row.productId);
    if (!product) continue; // no longer sold
    if (row.optionIndex < 0 || row.optionIndex >= product.options.length) continue;
    if (row.qty < 1) continue;
    const key = `${row.productId}|${row.optionIndex}`;
    result.set(key, {
      product,
      optionIndex: row.optionIndex,
      qty: Math.min(row.qty, MAX_QTY),
      note: row.note.slice(0, MAX_NOTE),
    });
  }
  return result;
}

export async function fetchCatalog(): Promise<Product[]> {
  const r = await fetch("/api/products", { credentials: "same-origin" });
  if (!r.ok) return [];
  const data = (await r.json()) as { products?: Product[] };
  return Array.isArray(data.products) ? data.products : [];
}
