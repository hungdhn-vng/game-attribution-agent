"use client";
import { makePkce, buildAuthorizeUrl, getToken, tokenIsFresh } from "@/lib/gaa/st-oauth";

export function SensorTowerConnect() {
  const connected = tokenIsFresh(getToken(), Math.floor(Date.now() / 1000));
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
  return <button onClick={connect}>{connected ? "Sensor Tower ✓" : "Connect Sensor Tower"}</button>;
}
