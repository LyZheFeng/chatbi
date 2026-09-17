// SSE 消费:fetch + ReadableStream(EventSource 不支持自定义头,chatbi 需要 X-API-Key)
// 帧格式:`event: <name>\ndata: <json>\n\n`

export type SseCallback = (event: string, data: unknown) => void;

export async function streamSse(
  url: string,
  onEvent: SseCallback,
  signal?: AbortSignal,
  headers?: Record<string, string>,
): Promise<void> {
  const resp = await fetch(url, { signal, headers });
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(event, JSON.parse(data));
    }
  }
}
