import { getSession } from "next-auth/react";
import { auth } from "@/auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

/**
 * Automatically extracts the JWT from the NextAuth session and appends it to requests.
 * Works on both client and server side.
 */
export async function fetchWithAuth(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  let session;
  
  if (typeof window === "undefined") {
    // Server-side
    session = await auth();
  } else {
    // Client-side
    session = await getSession();
  }

  const token = session?.user?.accessToken;

  const headers = new Headers(options.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  // Ensure content-type is set if there's a body and it's not FormData
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${BACKEND_URL}${endpoint}`, {
    ...options,
    headers,
  });

  return res;
}
