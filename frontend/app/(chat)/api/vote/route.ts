// DB removed — voting is a no-op until backend is wired.
export async function GET() {
  return Response.json([], { status: 200 });
}

export async function PATCH() {
  return new Response("ok", { status: 200 });
}
