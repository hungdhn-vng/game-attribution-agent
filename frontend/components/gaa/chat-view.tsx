"use client";

/**
 * ChatView — styled chat panel + composer (U2)
 *
 * Prop contract (for U3):
 *   onMessages?: (msgs: Turn[]) => void
 *     Called whenever the message list changes. U3 can derive:
 *       - latestRunId: msgs.at(-1)?.runId ?? null
 *       - all runIds: msgs.map(m=>m.runId).filter(Boolean)
 *     This keeps ChatView focused purely on chat; the parent page drives
 *     the dossier pane from the bubbled message list.
 *
 * Design:
 *   - Reuses MessageReasoning (clone's collapsible reasoning component)
 *   - Reuses MessageContent + MessageResponse (markdown rendering)
 *   - Reuses Greeting (empty-state animation)
 *   - Reuses ThinkingMessage (shimmer "Thinking..." row)
 *   - Reuses PromptInput / PromptInputTextarea / PromptInputFooter /
 *     PromptInputTools / PromptInputSubmit — exact same composer primitives
 *     as multimodal-input.tsx, stripped of model-picker + slash-commands
 *   - Mirrors exact bubble className strings from message.tsx for visual parity
 */

import { ArrowUpIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Greeting } from "@/components/chat/greeting";
import { PaperclipIcon, SparklesIcon, StopIcon } from "@/components/chat/icons";
import { MessageReasoning } from "@/components/chat/message-reasoning";
import { ThinkingMessage } from "@/components/chat/message";
import {
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { ActivityStrip } from "@/components/gaa/activity-strip";
import { UploadMapping } from "@/components/gaa/upload-mapping";
import { useConversations } from "@/components/gaa/conversation-store";
import { useGaaChat, type Turn } from "@/components/gaa/use-gaa-chat";
import { loadConversation, saveConversation } from "@/lib/gaa/store";
import { cn } from "@/lib/utils";

export interface ChatViewProps {
  /** Called on every messages state change; U3 uses this to drive the dossier pane. */
  onMessages?: (msgs: Turn[]) => void;
}

export function ChatView({ onMessages }: ChatViewProps) {
  const { activeId, refresh } = useConversations();
  const { messages, streaming, send, setMessages } = useGaaChat();

  // Local composer state
  const [input, setInput] = useState("");

  // CSV upload state
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll ref
  const bottomRef = useRef<HTMLDivElement>(null);

  // ── Load conversation when activeId changes ──────────────────────────────
  useEffect(() => {
    const stored = loadConversation(activeId);
    setMessages(stored as Turn[]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // ── Persist conversation whenever messages change ────────────────────────
  useEffect(() => {
    if (messages.length === 0) return;
    const title = messages[0]?.content?.slice(0, 60) ?? "Chat";
    saveConversation(activeId, title, messages);
    refresh(); // update sidebar title
  }, [messages, activeId, refresh]);

  // ── Bubble messages up so U3 can derive runIds / latestRunId ────────────
  useEffect(() => {
    onMessages?.(messages);
  }, [messages, onMessages]);

  // ── Auto-scroll to bottom on new messages ───────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── Send handler ─────────────────────────────────────────────────────────
  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    send(text);
  }, [input, streaming, send]);

  // ── Determine "is thinking" state for last assistant message ─────────────
  const lastMsg = messages.at(-1);
  const isThinkingPhase =
    streaming &&
    lastMsg?.role === "assistant" &&
    !lastMsg.content &&
    !(lastMsg.thinking?.length) &&
    !(lastMsg.activity?.length);

  return (
    <div className="flex h-full flex-col">
      {/* ── Message list ──────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-2">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <Greeting />
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-5 px-2 py-6">
            {messages.map((msg, idx) => (
              <GaaMessageRow key={idx} msg={msg} streaming={streaming} isLast={idx === messages.length - 1} />
            ))}

            {/* ThinkingMessage shimmer when streaming hasn't produced anything yet */}
            {isThinkingPhase && <ThinkingMessage />}

            {/* CSV upload widget inline above composer */}
            {pendingFile && (
              <div className="mx-auto w-full max-w-4xl">
                <UploadMapping
                  file={pendingFile}
                  onDone={(resultMsg) => {
                    setPendingFile(null);
                    setMessages((cur) => [
                      ...cur,
                      { role: "assistant", content: resultMsg },
                    ]);
                  }}
                />
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* ── Composer ──────────────────────────────────────────────────────── */}
      <div className="mx-auto w-full max-w-4xl px-4 pb-4 pt-2">
        {/* Pending CSV widget shown above composer when list is empty */}
        {pendingFile && messages.length === 0 && (
          <div className="mb-2">
            <UploadMapping
              file={pendingFile}
              onDone={(resultMsg) => {
                setPendingFile(null);
                setMessages((cur) => [
                  ...cur,
                  { role: "assistant", content: resultMsg },
                ]);
              }}
            />
          </div>
        )}

        {/* Hidden CSV file input */}
        <input
          accept=".csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setPendingFile(f);
            e.target.value = "";
          }}
          ref={csvInputRef}
          type="file"
        />

        <PromptInput
          className="[&>div]:rounded-2xl [&>div]:border [&>div]:border-border/30 [&>div]:bg-card/70 [&>div]:shadow-[var(--shadow-composer)] [&>div]:transition-shadow [&>div]:duration-300 [&>div]:focus-within:shadow-[var(--shadow-composer-focus)]"
          onSubmit={() => {
            handleSend();
          }}
        >
          <PromptInputTextarea
            className="min-h-24 px-4 pb-1.5 pt-3.5 text-[13px] leading-relaxed placeholder:text-muted-foreground/35"
            data-testid="gaa-chat-input"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask anything..."
            value={input}
          />
          <PromptInputFooter className="px-3 pb-3">
            <PromptInputTools>
              {/* CSV upload button */}
              <Button
                className="h-7 w-7 rounded-lg border border-border/40 p-1 text-foreground transition-colors hover:border-border hover:text-foreground"
                data-testid="csv-upload-button"
                disabled={streaming}
                onClick={(e) => {
                  e.preventDefault();
                  csvInputRef.current?.click();
                }}
                type="button"
                variant="ghost"
              >
                <PaperclipIcon size={14} style={{ width: 14, height: 14 }} />
              </Button>
            </PromptInputTools>

            {streaming ? (
              /* Stop button while streaming */
              <Button
                className="h-7 w-7 rounded-xl bg-foreground p-1 text-background transition-all duration-200 hover:opacity-85 active:scale-95"
                data-testid="stop-button"
                onClick={(e) => {
                  e.preventDefault();
                  // useGaaChat doesn't expose stop(), so we just disable — a noop stop
                }}
                type="button"
              >
                <StopIcon size={14} />
              </Button>
            ) : (
              <PromptInputSubmit
                className={cn(
                  "h-7 w-7 rounded-xl transition-all duration-200",
                  input.trim()
                    ? "bg-foreground text-background hover:opacity-85 active:scale-95"
                    : "cursor-not-allowed bg-muted text-muted-foreground/25"
                )}
                data-testid="send-button"
                disabled={!input.trim() || streaming}
                variant="secondary"
              >
                <ArrowUpIcon className="size-4" />
              </PromptInputSubmit>
            )}
          </PromptInputFooter>
        </PromptInput>
      </div>
    </div>
  );
}

// ── Per-message row ───────────────────────────────────────────────────────────

interface GaaMessageRowProps {
  msg: Turn;
  streaming: boolean;
  isLast: boolean;
}

function GaaMessageRow({ msg, streaming, isLast }: GaaMessageRowProps) {
  const isUser = msg.role === "user";
  const isAssistant = msg.role === "assistant";

  // Build joined reasoning text from our Think[] array
  const reasoningText = msg.thinking
    ?.map((t) => (t.scope ? `**${t.scope}**\n${t.text}` : t.text))
    .join("\n\n") ?? "";

  // "is this message still actively streaming reasoning?"
  const isReasoningStreaming = isLast && streaming && !msg.content;

  return (
    <div
      className={cn(
        "group/message w-full",
        !isAssistant && "animate-[fade-up_0.25s_cubic-bezier(0.22,1,0.36,1)]"
      )}
      data-role={msg.role}
      data-testid={`message-${msg.role}`}
    >
      <div
        className={cn(
          isUser ? "flex flex-col items-end gap-2" : "flex items-start gap-3"
        )}
      >
        {/* Assistant badge */}
        {isAssistant && (
          <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
            <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
              <SparklesIcon size={13} />
            </div>
          </div>
        )}

        {/* Content column */}
        {isAssistant ? (
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            {/* Collapsible reasoning — reuses clone's MessageReasoning */}
            {reasoningText && (
              <MessageReasoning
                isLoading={isReasoningStreaming}
                reasoning={reasoningText}
              />
            )}

            {/* Activity events */}
            <ActivityStrip activity={msg.activity} />

            {/* Main text content */}
            {msg.content && (
              <MessageContent
                className="text-[13px] leading-[1.65]"
                data-testid="message-content"
              >
                <MessageResponse>{msg.content}</MessageResponse>
              </MessageContent>
            )}
          </div>
        ) : (
          /* User bubble — exact className from message.tsx */
          <MessageContent
            className={cn(
              "text-[13px] leading-[1.65]",
              "w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-2xl rounded-br-lg border border-border/30 bg-gradient-to-br from-secondary to-muted px-3.5 py-2 shadow-[var(--shadow-card)]"
            )}
            data-testid="message-content"
          >
            <MessageResponse>{msg.content}</MessageResponse>
          </MessageContent>
        )}
      </div>
    </div>
  );
}
