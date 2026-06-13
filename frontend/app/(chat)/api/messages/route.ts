// DB removed — messages are ephemeral (in-memory via useChat). Return empty for now.
export async function GET() {
  return Response.json({
    messages: [],
    visibility: "private",
    userId: "local",
    isReadonly: false,
  });
}
