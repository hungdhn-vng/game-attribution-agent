export type Msg = { role: "user" | "assistant"; content: string };
type Meta = { id: string; title: string; updated: number };

const INDEX = "gaa:conversations";
const key = (id: string) => `gaa:conv:${id}`;

export function listConversations(): Meta[] {
  if (typeof localStorage === "undefined") return [];
  try {
    return (JSON.parse(localStorage.getItem(INDEX) ?? "[]") as Meta[])
      .sort((a, b) => b.updated - a.updated);
  } catch {
    return [];
  }
}

export function loadConversation(id: string): Msg[] {
  if (typeof localStorage === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(key(id)) ?? "[]") as Msg[];
  } catch {
    return [];
  }
}

export function saveConversation(id: string, title: string, messages: Msg[]): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(key(id), JSON.stringify(messages));
  const index = listConversations().filter((c) => c.id !== id);
  index.push({ id, title: title.slice(0, 60), updated: Date.now() });
  localStorage.setItem(INDEX, JSON.stringify(index));
}
