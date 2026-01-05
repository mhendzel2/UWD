import { ToastInput } from "../state/user";

export async function handleAuthFailure(res: Response, pushToast: (toast: ToastInput) => void): Promise<boolean> {
  if (res.status === 401) {
    pushToast({ tone: "error", message: "Authentication required for this action." });
    return true;
  }
  if (res.status === 403) {
    const detail = await res.text();
    pushToast({
      tone: "error",
      message: detail || "You are not authorized to perform this action.",
    });
    return true;
  }
  return false;
}
