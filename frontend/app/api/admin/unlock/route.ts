import { NextResponse } from "next/server";
import crypto from "node:crypto";
import { signAdmin } from "@/lib/gaa/admin-cookie";

const EIGHT_HOURS = 8 * 60 * 60 * 1000;

function constEq(a: string, b: string): boolean {
  const ab = Buffer.from(a), bb = Buffer.from(b);
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

export async function POST(req: Request) {
  const { passphrase } = await req.json().catch(() => ({ passphrase: "" }));
  const expected = process.env.GAA_ADMIN_PASSPHRASE ?? "";
  if (!expected || !constEq(String(passphrase ?? ""), expected)) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }
  const cookie = signAdmin(process.env.GAA_COOKIE_SECRET ?? "", Date.now() + EIGHT_HOURS);
  const res = NextResponse.json({ ok: true });
  res.cookies.set("gaa_admin", cookie, {
    httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: EIGHT_HOURS / 1000,
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete("gaa_admin");
  return res;
}
