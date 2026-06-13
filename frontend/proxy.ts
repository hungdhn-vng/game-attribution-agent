import { type NextRequest, NextResponse } from "next/server";

// Auth is a local stub (lib/auth/index.ts) — no NextAuth session required.
// All requests pass through; no redirect to /api/auth/guest.
export async function proxy(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/chat/:id",
    "/api/:path*",
    "/login",
    "/register",

    "/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
