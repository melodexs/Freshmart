/** Minimal typing for the parts of HTMX this app calls. */
interface HtmxApi {
  ajax(method: "GET" | "POST", url: string, opts: { target: string; swap?: string }): Promise<void>;
}

interface Window {
  htmx: HtmxApi;
}
