export function scoreBadgeClasses(pct: number): string {
  if (pct >= 80) return "bg-success-soft text-success";
  if (pct >= 60) return "bg-warning-soft text-warning";
  return "bg-surface-alt text-muted";
}
