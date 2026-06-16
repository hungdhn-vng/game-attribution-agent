"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { makePkce, buildAuthorizeUrl, getToken, tokenIsFresh } from "@/lib/gaa/st-oauth";

export function SensorTowerConnect() {
  // Read browser-only state (sessionStorage + Date.now) AFTER mount, never during
  // render/prerender — Next.js forbids Date.now()/sessionStorage in a client component's
  // render path (prerender error), and it keeps the connected label fresh on mount.
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    setConnected(tokenIsFresh(getToken(), Math.floor(Date.now() / 1000)));
  }, []);
  const connect = async () => {
    const { verifier, challenge } = await makePkce();
    const state = crypto.randomUUID();
    sessionStorage.setItem("st_verifier", verifier);
    sessionStorage.setItem("st_state", state);
    window.location.href = buildAuthorizeUrl({
      base: process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2",
      clientId: process.env.NEXT_PUBLIC_ST_CLIENT_ID || "",
      redirectUri: `${window.location.origin}/sensor-tower/connected`,
      state, challenge,
    });
  };
  return (
    <Button
      className="h-7 rounded-lg border border-border/40 px-2 text-xs text-foreground transition-colors hover:border-border hover:text-foreground"
      onClick={(e) => { e.preventDefault(); void connect(); }}
      type="button"
      variant="ghost"
    >
      {connected ? "Sensor Tower ✓" : "Connect Sensor Tower"}
    </Button>
  );
}
