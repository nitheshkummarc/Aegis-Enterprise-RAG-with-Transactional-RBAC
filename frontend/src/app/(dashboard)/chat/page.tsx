"use client";

import React, { useState, FormEvent, useRef, useEffect } from "react";
import { useSession, signOut } from "next-auth/react";
import { fetchWithAuth } from "@/lib/api";
import SourcesDropdown, { Source } from "@/components/SourcesDropdown";
import { Send, Bot, User, Loader2, Shield } from "lucide-react";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
};

export default function ChatPage() {
  const { data: session } = useSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    setInput("");
    
    // Add user message to UI immediately
    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: userMsg,
    };
    
    const aiMessageId = (Date.now() + 1).toString();
    const aiMessage: Message = {
      id: aiMessageId,
      role: "assistant",
      content: "",
    };

    setMessages((prev) => [...prev, userMessage, aiMessage]);
    setIsLoading(true);

    try {
      const res = await fetchWithAuth("/retrieval/query", {
        method: "POST",
        body: JSON.stringify({ question: userMsg }),
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
                } else if (event.type === "done") {
                  // Final event with sources
                  setMessages((prev) => 
                    prev.map((msg) => 
                      msg.id === aiMessageId ? { ...msg, sources: event.sources } : msg
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
            ? { ...msg, content: "Sorry, an error occurred while generating the response." } 
            : msg
        )
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-4xl mx-auto bg-neutral-950 rounded-lg shadow-sm border border-neutral-800 mt-6 overflow-hidden">
      {/* Header */}
      <div className="bg-neutral-900 p-4 border-b border-neutral-800 flex justify-between items-center">
        <h2 className="text-lg font-semibold text-neutral-100">Aegis Terminal</h2>
        <div className="text-sm text-neutral-400 flex items-center">
          <Shield className="w-4 h-4 mr-1" />
          Clearance Level: <span className="font-bold text-neutral-200 ml-1 uppercase">{session?.user?.role || "unknown"}</span>
          <button 
            onClick={() => signOut()} 
            className="ml-4 px-3 py-1 bg-neutral-800 hover:bg-neutral-700 border border-neutral-700 text-neutral-300 rounded text-xs transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-neutral-500">
            <Bot className="w-12 h-12 mb-2 text-neutral-700" />
            <p>Ask a question based on your clearance level.</p>
          </div>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`flex max-w-[80%] ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${msg.role === "user" ? "bg-neutral-800 text-neutral-300 ml-3" : "bg-neutral-800 text-neutral-300 mr-3"}`}>
                  {msg.role === "user" ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
                </div>
                <div>
                  <div className={`p-4 rounded-lg ${msg.role === "user" ? "bg-neutral-800 border border-neutral-700 text-neutral-100" : "bg-neutral-900 border border-neutral-800 text-neutral-200"}`}>
                    <p className="whitespace-pre-wrap">{msg.content || (msg.role === "assistant" && <span className="animate-pulse">Thinking...</span>)}</p>
                  </div>
                  {msg.role === "assistant" && msg.sources !== undefined && (
                    <SourcesDropdown 
                      sources={msg.sources} 
                      userRole={session?.user?.role || "viewer"} 
                    />
                  )}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="bg-neutral-900 p-4 border-t border-neutral-800">
        <form onSubmit={handleSubmit} className="flex relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your query here..."
            className="flex-1 border border-neutral-700 bg-neutral-950 text-neutral-100 rounded-full pl-6 pr-14 py-3 focus:outline-none focus:ring-2 focus:ring-neutral-500 focus:border-transparent transition-all placeholder-neutral-500"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="absolute right-2 top-2 bottom-2 bg-neutral-700 text-neutral-100 rounded-full w-10 h-10 flex items-center justify-center hover:bg-neutral-600 disabled:opacity-50 transition-colors"
          >
            {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </button>
        </form>
      </div>
    </div>
  );
}
