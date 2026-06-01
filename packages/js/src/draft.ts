/**
 * draft — turn an observed Catalog into a starter KIFF domain.
 *
 * The instrument-first authoring payoff: the same integration the
 * developer added for runtime governance also drafts the domain.
 *
 * Honesty boundary:
 *   - DERIVED from traffic: the action catalog + parameter shapes.
 *   - NOT derivable from tool signatures: the state machine, per-action
 *     risk, approval policy. Left as explicit TODO for a human / Template.
 *
 * 1:1 port of the Python SDK's export_yaml.
 */

import { Catalog } from "./catalog.js";

export function exportYaml(domainName: string, catalog: Catalog): string {
  const lines: string[] = [];
  lines.push(`# KIFF domain draft for '${domainName}'`);
  lines.push("# Auto-derived from observed agent traffic (instrument-first).");
  lines.push("# Catalog + parameter shapes are derived; risk, states, and");
  lines.push("# approval policy are TODO — the human's judgment goes here.");
  lines.push("");
  lines.push(`domain: ${domainName}`);
  lines.push("");
  lines.push("# Agents observed acting in this tenant:");
  for (const agent of [...catalog.agents].sort()) {
    lines.push(`#   - ${agent}`);
  }
  lines.push("");
  lines.push("# TODO(human): define the entity state machine. Derived");
  lines.push("# traffic cannot tell us the lifecycle (e.g. CREATED ->");
  lines.push("# PAID -> REFUNDED). Studio or a template seeds this.");
  lines.push("states: []   # TODO");
  lines.push("");
  lines.push("actions:");
  for (const tool of [...catalog.tools.keys()].sort()) {
    const params = [...(catalog.tools.get(tool) ?? new Set<string>())].sort();
    lines.push(`  - name: ${tool}`);
    lines.push("    parameters:");
    for (const p of params) {
      lines.push(`      - ${p}`);
    }
    lines.push("    risk: low            # TODO(human): low | medium | high");
    lines.push("    requires_approval: false   # TODO(human)");
    lines.push("    allowed_states: []   # TODO(human): which states allow this");
    lines.push("");
  }
  return lines.join("\n").replace(/\s+$/, "") + "\n";
}
