// DB removed — document API is a no-op stub.

export async function GET() {
  return Response.json([], { status: 200 });
}

export async function POST(_request: Request) {
  return Response.json(null, { status: 200 });
}

export async function DELETE() {
  return Response.json(null, { status: 200 });
}
