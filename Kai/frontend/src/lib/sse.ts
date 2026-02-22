export type SSEEventHandler = (eventType: string, data: Record<string, unknown>) => void;

// SSE must bypass Next.js rewrites (which buffer the response).
// Call the backend directly for true streaming.
const SSE_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://localhost:8000";

export async function streamSSE(
  url: string,
  body: Record<string, unknown>,
  onEvent: SSEEventHandler,
  onError?: (error: Error) => void,
  onComplete?: () => void
): Promise<void> {
  try {
    const response = await fetch(`${SSE_BASE}${url}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`SSE request failed: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No readable stream available");
    }

    const decoder = new TextDecoder();
    let buffer = "";
    let currentEventType = "message";
    let dataLines: string[] = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      // Keep the last incomplete line in the buffer
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();

        if (trimmed === "") {
          // Empty line = end of event: parse accumulated data
          if (dataLines.length > 0) {
            const dataStr = dataLines.join("\n");
            try {
              const parsed = JSON.parse(dataStr);
              onEvent(currentEventType, parsed);
            } catch {
              onEvent(currentEventType, { raw: dataStr });
            }
          }
          currentEventType = "message";
          dataLines = [];
          continue;
        }

        if (trimmed.startsWith("event:")) {
          currentEventType = trimmed.slice(6).trim();
        } else if (trimmed.startsWith("data:")) {
          dataLines.push(trimmed.slice(5).trim());
        }
      }
    }

    // Flush any remaining data
    if (dataLines.length > 0) {
      const dataStr = dataLines.join("\n");
      try {
        const parsed = JSON.parse(dataStr);
        onEvent(currentEventType, parsed);
      } catch {
        onEvent(currentEventType, { raw: dataStr });
      }
    }

    onComplete?.();
  } catch (error) {
    onError?.(error instanceof Error ? error : new Error(String(error)));
  }
}
