// Stub queries — DB removed. All functions are no-ops or return empty data.
// Document/suggestion tools remain structurally intact but won't persist.

import "server-only";

import type {
  Chat,
  DBMessage,
  Document,
  Stream,
  Suggestion,
  User,
  Vote,
} from "./schema";

// ── User ──────────────────────────────────────────────────────────────────────

export async function getUser(_email: string): Promise<User[]> {
  return [];
}

export async function createUser(_email: string, _password: string) {
  return [];
}

export async function createGuestUser() {
  return [{ id: "local", email: "local@localhost", type: "regular" }];
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export async function saveChat(_: {
  id: string;
  userId: string;
  title: string;
  visibility: string;
}): Promise<void> {}

export async function deleteChatById(_: { id: string }) {
  return null;
}

export async function getChatsByUserId(_: {
  id: string;
  limit: number;
  startingAfter?: string | null;
  endingBefore?: string | null;
}): Promise<{ chats: Chat[]; hasMore: boolean }> {
  return { chats: [], hasMore: false };
}

export async function getChatById(_: {
  id: string;
}): Promise<Chat | null> {
  return null;
}

export async function updateChatTitleById(_: {
  chatId: string;
  title: string;
}): Promise<void> {}

export async function updateChatVisibilityById(_: {
  chatId: string;
  visibility: string;
}): Promise<void> {}

export async function deleteAllChatsByUserId(_: {
  userId: string;
}): Promise<{ deleted: number }> {
  return { deleted: 0 };
}

// ── Message ───────────────────────────────────────────────────────────────────

export async function saveMessages(_: {
  messages: Array<{
    id: string;
    chatId: string;
    role: string;
    parts: unknown;
    attachments: unknown;
    createdAt: Date;
  }>;
}): Promise<void> {}

export async function getMessagesByChatId(_: {
  id: string;
}): Promise<DBMessage[]> {
  return [];
}

export async function getMessageById(_: { id: string }): Promise<DBMessage[]> {
  return [];
}

export async function deleteMessagesByChatIdAfterTimestamp(_: {
  chatId: string;
  timestamp: Date;
}): Promise<void> {}

export async function updateMessage(_: {
  id: string;
  parts: unknown;
}): Promise<void> {}

export async function getMessageCountByUserId(_: {
  id: string;
  differenceInHours: number;
}): Promise<number> {
  return 0;
}

// ── Vote ──────────────────────────────────────────────────────────────────────

export async function getVotesByChatId(_: { id: string }): Promise<Vote[]> {
  return [];
}

export async function voteMessage(_: {
  chatId: string;
  messageId: string;
  type: "up" | "down";
}): Promise<void> {}

// ── Document ──────────────────────────────────────────────────────────────────

export async function getDocumentById(_: {
  id: string;
}): Promise<Document | null> {
  return null;
}

export async function saveDocument(_: {
  id: string;
  title: string;
  kind: string;
  content: string;
  userId: string;
}): Promise<void> {}

export async function getDocumentsByIdAfterTimestamp(_: {
  id: string;
  timestamp: Date;
}): Promise<Document[]> {
  return [];
}

export async function deleteDocumentsByIdAfterTimestamp(_: {
  id: string;
  timestamp: Date;
}): Promise<void> {}

// ── Suggestion ────────────────────────────────────────────────────────────────

export async function saveSuggestions(_: {
  suggestions: Suggestion[];
}): Promise<void> {}

export async function getSuggestionsByDocumentId(_: {
  documentId: string;
}): Promise<Suggestion[]> {
  return [];
}

// ── Stream ────────────────────────────────────────────────────────────────────

export async function createStreamId(_: {
  streamId: string;
  chatId: string;
}): Promise<void> {}

export async function getStreamIdsByChatId(_: {
  chatId: string;
}): Promise<Stream[]> {
  return [];
}
