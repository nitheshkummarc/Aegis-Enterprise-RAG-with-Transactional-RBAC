"use client";

import React, { useState, FormEvent, useRef, useEffect, KeyboardEvent } from "react";
import { useSession, signOut } from "next-auth/react";
import { fetchWithAuth } from "@/lib/api";
import SourcesDropdown, { Source } from "@/components/SourcesDropdown";
import { Send, Bot, User, Loader2, ShieldCheck, LogOut, Sparkles } from "lucide-react";
import { roleInfo } from "@/lib/roles";
import { cn } from "@/lib/utils";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  generationError?: boolean;
  streaming?: boolean;
};

export default function ChatPage() {
  const { data: session } = useSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const role = roleInfo(session?.user?.role);
  const RoleIcon = role.icon;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize the textarea as the user types, capped by max-h in the class.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const sendQuestion = async (question: string) => {
    if (!question.trim() || isLoading) return;

    setInput("");

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: question,
    };

    const aiMessageId = (Date.now() + 1).toString();
    const aiMessage: Message = {
      id: aiMessageId,
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMessage, aiMessage]);
    setIsLoading(true);

    try {
      const res = await fetchWithAuth("/retrieval/query", {
        method: "POST",
        body: JSON.stringify({ question }),
      });

      if (!res.ok || !res.body) {
        throw new Error("Failed to fetch from backend");
      }

      // ------------------------------------------------------------------
      // SSE Parsing Logic (Phase 4 Requirement)
      // Accumulate type: "token" events and render sources on type: "done"
      // ------------------------------------------------------------------
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let doneReading = false;
      let aiContent = "";

      while (!doneReading) {
        const { value, done } = await reader.read();
        doneReading = done;

        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          // Split by SSE double newline boundary
          const lines = chunk.split("\n\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const dataStr = line.replace("data: ", "").trim();
              if (!dataStr) continue;

              try {
                const event = JSON.parse(dataStr);

                if (event.type === "token") {
                  aiContent += event.text;

                  // Update message continuously
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === aiMessageId ? { ...msg, content: aiContent } : msg
                    )
                  );
                } else if (event.type === "error") {
                  // Generation failed — distinct from an RBAC refusal (empty
                  // sources on "done"). The following "done" still carries
                  // the real permitted sources.
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === aiMessageId ? { ...msg, generationError: true } : msg
                    )
                  );
                } else if (event.type === "done") {
                  // Final event with sources
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === aiMessageId
                        ? { ...msg, sources: event.sources, streaming: false }
                        : msg
                    )
                  );
                }
              } catch (err) {
                console.error("Error parsing SSE event:", err, dataStr);
              }
            }
          }
        }
      }
    } catch (error) {
      console.error("Chat error:", error);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === aiMessageId
            ? {
                ...msg,
                content: "Sorry, an error occurred while generating the response.",
                streaming: false,
              }
            : msg
        )
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await sendQuestion(input);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuestion(input);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-4xl mx-auto bg-neutral-950/60 rounded-2xl shadow-2xl shadow-black/30 border border-neutral-800 mt-6 overflow-hidden">
      {/* Header */}
      <div className="relative bg-neutral-900/80 backdrop-blur-sm p-4 border-b border-neutral-800 flex justify-between items-center shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-sky-500/15 flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-sky-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-neutral-100 leading-tight">
              Aegis Terminal
            </h2>
            <p className="text-[11px] text-neutral-500 leading-tight">
              Ask anything within your clearance
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-full border",
              role.badgeBg
            )}
          >
            <RoleIcon className="w-3.5 h-3.5" />
            <span className="uppercase tracking-wide">{role.label}</span>
          </div>
          <button
            onClick={() => signOut()}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-neutral-800 hover:bg-neutral-700 border border-neutral-700 text-neutral-300 rounded-full text-xs transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" />
            Sign Out
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="aegis-scroll flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="bg-neutral-900/80 backdrop-blur-sm p-4 border-t border-neutral-800 shrink-0">
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type your query here..."
              className={cn(
                "w-full resize-none border border-neutral-700 bg-neutral-950 text-neutral-100 rounded-2xl",
                "pl-5 pr-4 py-3 focus:outline-none focus:ring-2 focus:ring-sky-500/50 focus:border-sky-500/50",
                "transition-all placeholder-neutral-500 max-h-40 aegis-scroll"
              )}
              disabled={isLoading}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className={cn(
              "shrink-0 w-11 h-11 flex items-center justify-center rounded-full transition-all",
              "bg-sky-500 text-neutral-950 hover:bg-sky-400 hover:scale-105 active:scale-95",
              "disabled:opacity-40 disabled:hover:scale-100 disabled:bg-neutral-700 disabled:text-neutral-400"
            )}
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </form>
        <p className="mt-2 text-[11px] text-neutral-600 text-center">
          Enter to send &middot; Shift+Enter for a new line
        </p>
      </div>
    </div>
  );

  function EmptyState() {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center px-4 animate-fade-in">
        <div className="relative w-14 h-14 mb-4">
          <div className={cn("absolute inset-0 rounded-full blur-xl opacity-40", role.badgeBg)} />
          <div
            className={cn(
              "relative w-14 h-14 flex items-center justify-center rounded-full border",
              role.badgeBg
            )}
          >
            <Bot className="w-7 h-7" />
          </div>
        </div>
        <p className="text-neutral-200 font-medium mb-1">
          Ask a question based on your clearance level.
        </p>
        <p className="text-neutral-500 text-sm mb-6 max-w-sm">
          Every query runs through a permission-filtered SQL search before it
          ever reaches the model — try one of these to see it in action.
        </p>

        <div className="flex flex-col gap-2 w-full max-w-md">
          {role.samplePrompts.map((prompt) => (
            <button
              key={prompt}
              onClick={() => sendQuestion(prompt)}
              className={cn(
                "group flex items-center gap-2.5 text-left text-sm text-neutral-300 px-4 py-3 rounded-xl border",
                "bg-neutral-900/60 border-neutral-800 transition-all hover:-translate-y-0.5",
                role.chipBorder,
                role.chipBg
              )}
            >
              <Sparkles className={cn("w-3.5 h-3.5 shrink-0", role.accent)} />
              <span className="truncate">{prompt}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  function MessageBubble({ msg }: { msg: Message }) {
    const isUser = msg.role === "user";
    return (
      <div
        className={cn("flex animate-fade-up", isUser ? "justify-end" : "justify-start")}
      >
        <div className={cn("flex max-w-[85%] sm:max-w-[80%]", isUser ? "flex-row-reverse" : "flex-row")}>
          <div
            className={cn(
              "shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
              isUser ? "bg-neutral-800 text-neutral-300 ml-3" : cn(role.badgeBg, "mr-3")
            )}
          >
            {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <div
              className={cn(
                "p-4 rounded-2xl text-sm leading-relaxed",
                isUser
                  ? "bg-sky-500/10 border border-sky-500/20 text-neutral-100 rounded-tr-sm"
                  : "bg-neutral-900 border border-neutral-800 text-neutral-200 rounded-tl-sm"
              )}
            >
              <p className="whitespace-pre-wrap wrap-break-word">
                {msg.content}
                {msg.streaming && !msg.content && (
                  <span className="inline-flex items-center gap-1 text-neutral-500">
                    <span
                      className="w-1.5 h-1.5 rounded-full bg-neutral-500 animate-bounce"
                      style={{ animationDelay: "0ms" }}
                    />
                    <span
                      className="w-1.5 h-1.5 rounded-full bg-neutral-500 animate-bounce"
                      style={{ animationDelay: "150ms" }}
                    />
                    <span
                      className="w-1.5 h-1.5 rounded-full bg-neutral-500 animate-bounce"
                      style={{ animationDelay: "300ms" }}
                    />
                  </span>
                )}
                {msg.streaming && msg.content && (
                  <span className="inline-block w-1.5 h-4 bg-sky-400/70 ml-0.5 translate-y-0.5 animate-cursor" />
                )}
              </p>
            </div>
            {msg.role === "assistant" && msg.generationError && (
              <p className="text-xs text-amber-500 mt-1.5 px-1">
                Response generation failed — this was not an access restriction.
              </p>
            )}
            {msg.role === "assistant" && msg.sources !== undefined && (
              <SourcesDropdown sources={msg.sources} userRole={session?.user?.role || "viewer"} />
            )}
          </div>
        </div>
      </div>
    );
  }
}
