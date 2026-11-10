/** Small, typed DOM helpers. No innerHTML with untrusted text anywhere in this app. */

export function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Missing element #${id}`);
  return el as T;
}

export function $maybe<T extends HTMLElement = HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

type Attrs = Record<string, string | number | boolean | undefined>;

/** Build an element safely: text is always set with textContent, never parsed as HTML. */
export function h(
  tag: string,
  attrs: Attrs = {},
  ...children: (Node | string | null | undefined | false)[]
): HTMLElement {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === false) continue;
    if (k === "class") el.className = String(v);
    else if (k === "text") el.textContent = String(v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    el.append(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return el;
}

export const money = (n: number): string => "₦" + n.toLocaleString("en-NG");

export function show(el: HTMLElement): void {
  el.classList.add("show");
}
export function hide(el: HTMLElement): void {
  el.classList.remove("show");
}

/** Remove all children (safe alternative to innerHTML = ""). */
export function clear(el: HTMLElement): void {
  el.replaceChildren();
}

export function firstName(full: string): string {
  return full.split(" ")[0] ?? full;
}
