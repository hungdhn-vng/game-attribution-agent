"use client";
import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { listConversations, deleteConversation as del, clearAllConversations } from "@/lib/gaa/store";

type Conv = { id: string; title: string; updated: number };
type Ctx = {
  conversations: Conv[];
  activeId: string;
  refresh: () => void;
  setActive: (id: string) => void;
  newConversation: () => string;
  remove: (id: string) => void;
  removeAll: () => void;
};
const ConversationContext = createContext<Ctx | null>(null);

function genId(): string {
  return typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `c-${Date.now()}`;
}

export function ConversationProvider({ children }: { children: React.ReactNode }) {
  const [conversations, setConversations] = useState<Conv[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const refresh = useCallback(() => setConversations(listConversations()), []);
  useEffect(() => {
    const list = listConversations();
    setConversations(list);
    setActiveId(list[0]?.id ?? genId());
  }, []);
  const setActive = useCallback((id: string) => setActiveId(id), []);
  const newConversation = useCallback(() => {
    const id = genId();
    setActiveId(id);
    return id;
  }, []);
  const remove = useCallback((id: string) => {
    del(id);
    const list = listConversations();
    setConversations(list);
    setActiveId((cur) => (cur === id ? (list[0]?.id ?? genId()) : cur));
  }, []);
  const removeAll = useCallback(() => {
    clearAllConversations();
    setConversations([]);
    setActiveId(genId());
  }, []);
  return (
    <ConversationContext.Provider value={{ conversations, activeId, refresh, setActive, newConversation, remove, removeAll }}>
      {children}
    </ConversationContext.Provider>
  );
}

export function useConversations(): Ctx {
  const c = useContext(ConversationContext);
  if (!c) throw new Error("useConversations must be used within ConversationProvider");
  return c;
}
