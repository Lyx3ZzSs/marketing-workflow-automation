import type Keycloak from "keycloak-js";
import { redirectUri, logoutRedirectUri } from "./auth-config";
export { redirectUri, logoutRedirectUri } from "./auth-config";

export type AuthUser = {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
  department_code: string;
  department_name: string;
  roles: string[];
};

export const authConfig = {
  url: process.env.NEXT_PUBLIC_KEYCLOAK_URL ?? "http://10.8.6.32:18080",
  realm: process.env.NEXT_PUBLIC_KEYCLOAK_REALM ?? "company-dev",
  clientId: process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID ?? "marketing-workflow-automation-web",
};

// One initialization per document, including React Strict Mode's repeated effects.
// Tokens stay inside the adapter's memory; only its short-lived PKCE state uses storage.
let initialization: Promise<Keycloak> | undefined;
export function initializeAuth(): Promise<Keycloak> {
  initialization ??= import("keycloak-js").then(async ({ default: Keycloak }) => {
    const client = new Keycloak(authConfig);
    await client.init({
      onLoad: "login-required",
      flow: "standard",
      pkceMethod: "S256",
      checkLoginIframe: false,
      responseMode: "fragment",
      redirectUri: redirectUri(),
      scope: "profile email",
    });
    // login-required is only for initial navigation. The provider handles later
    // authentication failures; clearToken must not start a competing navigation.
    client.loginRequired = false;
    return client;
  });
  return initialization;
}

export function logoutSession(
  session: Pick<Keycloak, "createLogoutUrl" | "clearToken" | "loginRequired" | "onTokenExpired">,
  navigate: (url: string) => void = (url) => window.location.replace(url),
) {
  // Build the URL while the ID token is still available as id_token_hint.
  const url = session.createLogoutUrl({ redirectUri: logoutRedirectUri() });
  session.loginRequired = false;
  session.onTokenExpired = undefined;
  session.clearToken();
  navigate(url);
}

type TokenSession = Pick<Keycloak, "updateToken" | "token" | "clearToken">;
export class AuthenticationExpiredError extends Error {
  constructor() {
    super("登录已失效，请重新登录。");
  }
}

export function createAuthenticatedFetch(
  session: TokenSession,
  onRejected: (status: 401 | 403) => void,
  transport: typeof fetch = fetch,
) {
  return async (path: string, init: RequestInit = {}) => {
    // Never send the bearer token to external URLs or through redirects.
    if (!path.startsWith("/api/") || path.includes("\\"))
      throw new Error("认证请求必须使用本站 API 地址。");
    init.signal?.throwIfAborted();
    try {
      await session.updateToken(60);
      if (!session.token) throw new Error("Missing token");
    } catch {
      session.clearToken();
      onRejected(401);
      throw new AuthenticationExpiredError();
    }
    init.signal?.throwIfAborted();
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${session.token}`);
    const response = await transport(path, {
      ...init, headers, cache: "no-store", credentials: "omit", redirect: "error",
    });
    if (response.status === 401) session.clearToken();
    if (response.status === 401 || response.status === 403) onRejected(response.status);
    return response;
  };
}
