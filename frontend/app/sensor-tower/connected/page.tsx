"use client";
import { useEffect, useState } from "react";
import { exchangeCode, setToken } from "@/lib/gaa/st-oauth";

export default function Connected() {
  const [msg, setMsg] = useState("Connecting…");
  useEffect(() => {
    (async () => {
      const u = new URL(window.location.href);
      const code = u.searchParams.get("code");
      const state = u.searchParams.get("state");
      const err = u.searchParams.get("error");
      if (err) return setMsg(`Connection failed: ${err}`);
      const expected = sessionStorage.getItem("st_state");
      const verifier = sessionStorage.getItem("st_verifier");
      if (!code || !state || state !== expected || !verifier) return setMsg("Connection failed: bad state.");
      try {
        const t = await exchangeCode({
          base: process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2",
          clientId: process.env.NEXT_PUBLIC_ST_CLIENT_ID || "",
          redirectUri: `${window.location.origin}/sensor-tower/connected`,
          code, verifier,
        });
        setToken(t);
        sessionStorage.removeItem("st_state");      // single-use PKCE state/verifier — clear after exchange
        sessionStorage.removeItem("st_verifier");
        setMsg("✅ Connected — you can return to your chat.");
      } catch (e) {
        setMsg(`Connection failed: ${(e as Error).message}`);
      }
    })();
  }, []);
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: "32rem", margin: "4rem auto", textAlign: "center" }}>
      <h2>Sensor Tower</h2>
      <p>{msg}</p>
    </main>
  );
}
