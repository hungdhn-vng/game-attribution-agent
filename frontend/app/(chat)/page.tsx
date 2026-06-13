"use client";
/**
 * Chat page (U2 smoke-render).
 * Renders ChatView full-height in the inset.
 * U3 will add the dossier pane beside it and wire onMessages → ArtifactsPane.
 */
import { ChatView } from "@/components/gaa/chat-view";

export default function ChatPage() {
  return (
    <div className="flex h-full flex-col">
      <ChatView />
    </div>
  );
}
