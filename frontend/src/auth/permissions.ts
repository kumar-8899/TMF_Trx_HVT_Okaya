// Mirror of backend permission_granted (auth_verify.py): wildcard-aware.
// UX only — the API is the real gate (PRINCIPLES §3).
export function hasPermission(perms: string[] | undefined, needed: string): boolean {
  if (!perms || perms.length === 0) return false;
  if (perms.includes("*") || perms.includes(needed)) return true;
  const domain = needed.split(".")[0];
  return perms.includes(`${domain}.*`);
}
