/**
 * Catalog — the action surface derived from observed agent traffic.
 *
 * The honest half of instrument-first authoring: tool names and argument
 * shapes can be *derived* from real calls. Risk level, the state machine,
 * and approval policy cannot — they are human judgment, left as TODO in
 * the draft (see draft.ts). We never infer what we cannot.
 */
export class Catalog {
  /** One entry per distinct tool -> the set of argument keys seen. */
  readonly tools = new Map<string, Set<string>>();
  /** The set of agents observed acting in this tenant. */
  readonly agents = new Set<string>();

  record(agent: string, tool: string, args: Record<string, unknown>): void {
    this.agents.add(agent);
    let keys = this.tools.get(tool);
    if (!keys) {
      keys = new Set<string>();
      this.tools.set(tool, keys);
    }
    for (const k of Object.keys(args)) {
      keys.add(k);
    }
  }
}
