export type LogLevel = "info" | "warning" | "error";

export type LogEntry = {
  message: string;
  level?: LogLevel;
  timestamp: number;
};

export const LOG_BUFFER_LIMIT = 500;

export function appendLog(buffer: LogEntry[], entry: LogEntry): LogEntry[] {
  const next = [entry, ...buffer];
  if (next.length > LOG_BUFFER_LIMIT) {
    return next.slice(0, LOG_BUFFER_LIMIT);
  }
  return next;
}

export function formatLogMessage(entry: LogEntry): string {
  const time = new Date(entry.timestamp).toLocaleTimeString();
  const level = entry.level?.toUpperCase() ?? "INFO";
  return `[${time}] [${level}] ${entry.message}`;
}
