import { handleAuthFailure } from "./http";

describe("handleAuthFailure", () => {
  it("pushes an error toast on 403", async () => {
    const pushToast = vi.fn();
    const response = new Response("forbidden", { status: 403 });

    const handled = await handleAuthFailure(response, pushToast);

    expect(handled).toBe(true);
    expect(pushToast).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: "error",
      })
    );
  });
});
