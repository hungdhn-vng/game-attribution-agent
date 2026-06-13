"use client";
export function ActivityStrip({ activity }: { activity?: string[] }) {
  if (!activity?.length) return null;
  return (
    <div className="text-xs text-muted-foreground space-y-0.5 my-1">
      {activity.map((a, i) => <div key={i}>· {a}</div>)}
    </div>
  );
}
