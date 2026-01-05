import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { handleAuthFailure } from "../utils/http";

export type CapabilityKey = "compute_v0" | "compute_ecology" | "generate_briefs" | "compute_v1" | "compute_anomalies";

export type CapabilityState = {
  allowed: boolean;
  reason?: string | null;
};

export type CapabilityMap = Record<CapabilityKey, CapabilityState>;

export type ToastTone = "info" | "error";
export type ToastInput = { message: string; tone?: ToastTone };
export type Toast = ToastInput & { id: string; tone: ToastTone };

const defaultCapability: CapabilityState = { allowed: false, reason: "Capability unavailable" };
const buildDefaultCapabilities = (): CapabilityMap => ({
  compute_v0: { ...defaultCapability },
  compute_ecology: { ...defaultCapability },
  generate_briefs: { ...defaultCapability },
  compute_v1: { ...defaultCapability },
  compute_anomalies: { ...defaultCapability },
});

export const DEFAULT_CAPABILITIES: CapabilityMap = buildDefaultCapabilities();

type UserContextState = {
  token: string;
  setToken: (token: string) => void;
  role: string;
  capabilities: CapabilityMap;
  fetchCapabilities: (apiBase: string, sessionId: string) => Promise<void>;
  capabilityFor: (key: CapabilityKey) => CapabilityState;
  pushToast: (toast: ToastInput) => void;
  dismissToast: (id: string) => void;
  toasts: Toast[];
};

const UserStateContext = createContext<UserContextState | undefined>(undefined);

type ProviderProps = {
  children: React.ReactNode;
  initialToken?: string;
  initialCapabilities?: Partial<CapabilityMap>;
};

export const UserStateProvider: React.FC<ProviderProps> = ({ children, initialToken = "", initialCapabilities }) => {
  const [token, setToken] = useState<string>(initialToken);
  const [role, setRole] = useState<string>("unknown");
  const [capabilities, setCapabilities] = useState<CapabilityMap>({ ...buildDefaultCapabilities(), ...initialCapabilities });
  const [toasts, setToasts] = useState<Toast[]>([]);

  const pushToast = useCallback((toast: ToastInput) => {
    setToasts((prev) => [
      ...prev,
      {
        id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
        tone: toast.tone || "info",
        message: toast.message,
      },
    ]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    if (!toasts.length) return;
    const timer = setTimeout(() => {
      setToasts((prev) => prev.slice(1));
    }, 4000);
    return () => clearTimeout(timer);
  }, [toasts]);

  const capabilityFor = useCallback(
    (key: CapabilityKey): CapabilityState => capabilities[key] || defaultCapability,
    [capabilities]
  );

  const fetchCapabilities = useCallback(
    async (apiBase: string, sessionId: string) => {
      if (!sessionId) {
        pushToast({ tone: "error", message: "Select or create a session first." });
        return;
      }
      if (!token) {
        pushToast({ tone: "error", message: "Add an auth token to load capabilities." });
        setCapabilities(buildDefaultCapabilities());
        return;
      }

      const res = await fetch(`${apiBase}/sessions/${sessionId}/capabilities`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const handled = await handleAuthFailure(res, pushToast);
      if (handled) {
        setCapabilities(DEFAULT_CAPABILITIES);
        return;
      }

      if (!res.ok) {
        pushToast({ tone: "error", message: "Unable to load capabilities" });
        setCapabilities(buildDefaultCapabilities());
        return;
      }

      const json = await res.json();
      setCapabilities(json.capabilities || buildDefaultCapabilities());
      if (json.role) {
        setRole(json.role);
      }
    },
    [pushToast, token]
  );

  const value = useMemo(
    () => ({
      token,
      setToken,
      role,
      capabilities,
      fetchCapabilities,
      capabilityFor,
      pushToast,
      dismissToast,
      toasts,
    }),
    [token, role, capabilities, fetchCapabilities, capabilityFor, pushToast, dismissToast, toasts]
  );

  return <UserStateContext.Provider value={value}>{children}</UserStateContext.Provider>;
};

export function useUserState(): UserContextState {
  const ctx = useContext(UserStateContext);
  if (!ctx) throw new Error("useUserState must be used inside a UserStateProvider");
  return ctx;
}
