"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type Keycloak from "keycloak-js";
import { Button } from "@/components/ui/button";
import { AuthenticationExpiredError, createAuthenticatedFetch, initializeAuth, logoutSession, redirectUri, type AuthUser } from "@/lib/auth-client";

type AuthContextValue = {
  user: AuthUser;
  apiFetch: ReturnType<typeof createAuthenticatedFetch>;
  logout: () => void;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("Authentication is required");
  return auth;
}

type State =
  | { kind: "loading"; message?: string }
  | { kind: "signed-out"; message?: string }
  | { kind: "denied" }
  | { kind: "error"; message: string }
  | { kind: "ready"; user: AuthUser; apiFetch: AuthContextValue["apiFetch"] };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const client = useRef<Keycloak | null>(null);
  const redirecting = useRef(false);
  const reject = useCallback((status: 401 | 403) => {
    if (redirecting.current) return;
    setState(status === 403 ? { kind: "denied" } : { kind: "signed-out", message: "登录已失效，请重新登录。" });
  }, []);

  useEffect(() => {
    let active = true;
    let adapter: Keycloak | undefined;
    initializeAuth().then(async (keycloak) => {
      if (!active) return;
      adapter = keycloak;
      client.current = keycloak;
      if (window.location.pathname === "/callback") window.history.replaceState(null, "", "/");
      if (!keycloak.authenticated) {
        setState({ kind: "signed-out" });
        return;
      }
      const apiFetch = createAuthenticatedFetch(keycloak, (status) => { if (active) reject(status); });
      keycloak.onTokenExpired = () => {
        void keycloak.updateToken(60).catch(() => {
          keycloak.clearToken();
          if (active) reject(401);
        });
      };
      const response = await apiFetch("/api/me");
      if (!active || response.status === 401 || response.status === 403) return;
      if (!response.ok) throw new Error("身份校验服务暂时不可用，请稍后重试。");
      const user: AuthUser = await response.json();
      if (active) setState({ kind: "ready", user, apiFetch });
    }).catch((error) => {
      if (error instanceof AuthenticationExpiredError) return;
      if (active) setState({ kind: "error", message: "统一认证连接失败或登录回调无效，请重试。" });
    });
    return () => {
      active = false;
      if (adapter) adapter.onTokenExpired = undefined;
    };
  }, [reject]);

  useEffect(() => {
    if (state.kind !== "signed-out" || redirecting.current) return;
    const adapter = client.current;
    if (!adapter) return;
    redirecting.current = true;
    // Require a fresh login after session failure, avoiding an automatic SSO/401 loop.
    void adapter.login({ redirectUri: redirectUri(), prompt: "login" }).catch(() => {
      setState({ kind: "error", message: "无法打开统一登录，请重试。" });
    });
  }, [state.kind]);

  function logout() {
    const adapter = client.current;
    if (!adapter || redirecting.current) return;
    redirecting.current = true;
    setState({ kind: "loading", message: "正在退出登录…" });
    try {
      logoutSession(adapter);
    } catch {
      redirecting.current = false;
      setState({ kind: "error", message: "退出登录失败，请重试。" });
    }
  }

  if (state.kind === "ready") {
    return <AuthContext.Provider value={{ user: state.user, apiFetch: state.apiFetch, logout }}>{children}</AuthContext.Provider>;
  }
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#edf1e9] px-6">
      <section className="w-full max-w-md rounded-xl border bg-background p-9 shadow-sm" aria-labelledby="auth-title">
        <p className="mb-3 text-xs tracking-widest text-muted-foreground">FLOW APPROVAL</p>
        <h1 id="auth-title" className="font-serif text-3xl">流程自动审批</h1>
        <p role={state.kind === "error" || state.kind === "denied" ? "alert" : "status"} className="mt-5 text-sm leading-7 text-muted-foreground">
          {state.kind === "loading" ? state.message || "正在连接统一认证平台…" :
            state.kind === "denied" ? "当前账号没有访问权限，请联系管理员分配应用角色。" :
            state.kind === "error" ? state.message : "正在跳转到统一认证平台登录…"}
        </p>
        <div className="mt-7 flex gap-3">
          {state.kind === "denied" && <Button onClick={logout}>退出当前账号</Button>}
          {state.kind === "error" && <Button onClick={() => window.location.assign("/")}>重新连接</Button>}
          {state.kind === "error" && client.current?.authenticated && <Button variant="outline" onClick={logout}>退出登录</Button>}
        </div>
      </section>
    </main>
  );
}
