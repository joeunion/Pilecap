export async function request(): Promise<Response> {
  return fetch("/api/v1/deals/", { credentials: "same-origin" });
}
