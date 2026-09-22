/** Tabs internas — IDs preservados; overview redireciona para live. */
export type Tab =
  | "overview"
  | "live"
  | "students"
  | "report"
  | "review"
  | "system"
  | "school"
  | "history"
  | "settings"
  | "admin"
  | "lxpHomolog"
  | "facialEnrollment"
  | "platform";

export type WsState = "connecting" | "connected" | "disconnected";
