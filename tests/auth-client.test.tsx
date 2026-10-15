import assert from "node:assert/strict";
import test from "node:test";
import Keycloak from "keycloak-js";
import { createAuthenticatedFetch, logoutSession } from "../lib/auth-client";

test("logout clears a real Keycloak session without triggering login-required navigation", async () => {
  const session = new Keycloak({ url: "https://identity.example", realm: "test", clientId: "web" });
  session.loginRequired = true;
  session.authenticated = true;
  session.token = "test-access-token";
  session.idToken = "test-id-token";
  session.refreshToken = "test-refresh-token";
  session.onTokenExpired = () => assert.fail("Expiry callback must be disabled during logout");
  const navigations: string[] = [];
  session.login = async () => { await Promise.resolve(); navigations.push("login"); };
  session.createLogoutUrl = (options) => {
    assert.equal(session.idToken, "test-id-token", "ID token must exist when constructing the logout hint");
    assert.equal(options?.redirectUri, "http://127.0.0.1:4186/");
    return "https://identity.example/logout";
  };
  logoutSession(session, (url) => navigations.push(url));
  await Promise.resolve();
  assert.deepEqual(navigations, ["https://identity.example/logout"]);
  assert.equal(session.authenticated, false);
  assert.equal(session.token, undefined);
  assert.equal(session.idToken, undefined);
  assert.equal(session.refreshToken, undefined);
  assert.equal(session.onTokenExpired, undefined);
});

test("API calls refresh first and send only the current bearer token", async () => {
  const session = { token: "old", updateToken: async () => { session.token = "new"; return true; }, clearToken() {} };
  let called = false;
  const request = createAuthenticatedFetch(session, () => assert.fail("Unexpected auth rejection"), async (path, init) => {
    called = true;
    assert.equal(path, "/api/project-reviews");
    assert.equal(new Headers(init?.headers).get("authorization"), "Bearer new");
    assert.equal(new Headers(init?.headers).get("content-type"), "application/json");
    assert.equal(init?.body, '{"projectCode":"P1"}');
    assert.equal(init?.redirect, "error");
    assert.equal(init?.cache, "no-store");
    assert.equal(init?.credentials, "omit");
    return new Response("{}");
  });
  await request("/api/project-reviews", { method: "POST", body: '{"projectCode":"P1"}', headers: { "Content-Type": "application/json" } });
  assert.ok(called);
});

test("failed refresh clears identity and prevents business requests", async () => {
  const statuses: number[] = [];
  let cleared = false;
  const request = createAuthenticatedFetch({ token: "old", updateToken: async () => { throw new Error("expired"); }, clearToken: () => { cleared = true; } },
    (status) => statuses.push(status), async () => { throw new Error("Must not request data"); });
  await assert.rejects(request("/api/policy"), /登录已失效/);
  assert.ok(cleared);
  assert.deepEqual(statuses, [401]);
});

test("401 expires the session while 403 retains it for logout", async () => {
  for (const status of [401, 403]) {
    let cleared = false;
    const statuses: number[] = [];
    const request = createAuthenticatedFetch({ token: "token", updateToken: async () => false, clearToken: () => { cleared = true; } },
      (value) => statuses.push(value), async () => new Response("{}", { status }));
    assert.equal((await request("/api/policy")).status, status);
    assert.equal(cleared, status === 401);
    assert.deepEqual(statuses, [status]);
  }
});

test("external URLs are rejected before a token can be transmitted", async () => {
  const request = createAuthenticatedFetch({ token: "token", updateToken: async () => { assert.fail("Must not refresh"); }, clearToken() {} }, () => {},
    async () => { throw new Error("Must not request"); });
  for (const path of ["https://other.example/api/me", "//other.example/api/me", "/api\\other", "/outside"])
    await assert.rejects(request(path), /本站 API/);
});

test("network failures and cancelled requests do not sign the user out", async () => {
  const request = createAuthenticatedFetch({ token: "token", updateToken: async () => false, clearToken() { assert.fail("Must retain session"); } },
    () => assert.fail("Must retain identity"), async () => { throw new Error("offline"); });
  await assert.rejects(request("/api/policy"), /offline/);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(request("/api/policy", { signal: controller.signal }), { name: "AbortError" });
});
