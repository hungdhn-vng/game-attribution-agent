"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { makePkce, buildAuthorizeUrl, getToken, tokenIsFresh } from "@/lib/gaa/st-oauth";

export function SensorTowerConnect() {
  // Read browser-only state AFTER mount (Next forbids Date.now()/storage during render).
  // Refresh on the `storage` event so the label flips to ✓ when the OAuth popup stores
  // the token (the popup is a separate context; the write fires `storage` here).
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const sync = () => setConnected(tokenIsFresh(getToken(), Math.floor(Date.now() / 1000)));
    sync();
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  const connect = async () => {
    // Open the popup SYNCHRONOUSLY inside the click gesture (before any await) or browsers
    // block it; fill its URL once the async PKCE is ready. The main chat tab never navigates,
    // so the conversation is preserved. Falls back to a full redirect if the popup is blocked.
    const popup = window.open("", "st_connect", "width=520,height=680");
    const { verifier, challenge } = await makePkce();
    const state = crypto.randomUUID();
    localStorage.setItem("st_verifier", verifier);
    localStorage.setItem("st_state", state);
    const url = buildAuthorizeUrl({
      base: process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2",
      clientId: process.env.NEXT_PUBLIC_ST_CLIENT_ID || "",
      redirectUri: `${window.location.origin}/sensor-tower/connected`,
      state, challenge,
    });
    if (popup) popup.location.href = url;
    else window.location.href = url;
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
