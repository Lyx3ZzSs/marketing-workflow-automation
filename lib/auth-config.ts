// Shared by the browser adapter and the server's local-origin redirect.
export function redirectUri() {
  return process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI ?? "http://127.0.0.1:4186/callback";
}

export function logoutRedirectUri() {
  return process.env.NEXT_PUBLIC_KEYCLOAK_LOGOUT_REDIRECT_URI ?? new URL("/", redirectUri()).href;
}
