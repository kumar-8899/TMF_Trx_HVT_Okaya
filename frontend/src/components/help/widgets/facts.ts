/** Generated framework facts (docs/generated/facts.json via GET /help/facts, Developer Hub only).
 * One cached fetch shared by every widget on the page. */
import { useEffect, useState } from "react";

import { api } from "../../../api/client";

export interface Release { version: string; date: string; bump: string | null; summary: string; body: string }
export interface RouteRow { method: string; path: string }
export interface ModuleFact {
  id: string; display_name: string | null; description: string | null; version: string | null;
  contract_version: number | string | null; entitlement_key: string | null; variants: string[];
  api_prefix: string | null; core_dependencies: string[]; contract_dependencies: string[];
  permissions_used: string[]; routes: RouteRow[];
}
export interface PermissionFact { key: string; domain: string; label: string; description: string }
export interface StepTypeFact {
  type_id: string; display_name: string; composite: boolean; kind: string;
  required_signals: string[]; required_actions: string[]; schema: unknown;
}
export interface CapabilityFact {
  class: string; interface: string; interface_version: number; scalar: boolean; methods: string[];
}
export interface OpFact { op: string; group: string; blocking: boolean; doc: string }
export interface FrontendRoute { path: string; permission: string | null; role: string | null }
export interface SkillFact { name: string; description: string }

export interface Facts {
  schema_version: number;
  framework: { name: string; version: string };
  releases: Release[];
  modules: ModuleFact[];
  core: { routes: RouteRow[] };
  permissions: PermissionFact[];
  roles: Record<string, string[]>;
  step_types: StepTypeFact[];
  capabilities: CapabilityFact[];
  controller_ops: OpFact[];
  frontend_routes: FrontendRoute[];
  skills: SkillFact[];
}

let factsPromise: Promise<Facts> | null = null;

export function resetFactsCache(): void {
  factsPromise = null;
}

export function loadFacts(): Promise<Facts> {
  if (!factsPromise) {
    factsPromise = api.get("/help/facts");
    factsPromise.catch(() => { factsPromise = null; });
  }
  return factsPromise;
}

export function useFacts(): { facts: Facts | null; error: string | null } {
  const [facts, setFacts] = useState<Facts | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    loadFacts().then((f) => alive && setFacts(f)).catch((e) => alive && setError(e?.message ?? "facts unavailable"));
    return () => { alive = false; };
  }, []);
  return { facts, error };
}
