import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { isAdmin } from "@/lib/gaa/backend";

export async function GET() {
  const cookie = (await cookies()).get("gaa_admin")?.value;
  return NextResponse.json({ admin: isAdmin(cookie) });
}
