// Pass-through proxy in front of the static assets bundle.
//
// `run_worker_first` is on, so every request hits this fetch() — that's
// what makes invocation logs / traces non-empty. Behaviour is unchanged
// from the previous pure-assets setup: assets serve themselves, 404s go
// through `not_found_handling` from wrangler.jsonc.

export interface Env {
  ASSETS: Fetcher;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;
