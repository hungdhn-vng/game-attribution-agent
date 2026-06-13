// DB removed — chat history is local-only. Return empty list for now.
export async function GET() {
  return Response.json({ chats: [], hasMore: false });
}

export async function DELETE() {
  return Response.json({ deleted: 0 }, { status: 200 });
}
