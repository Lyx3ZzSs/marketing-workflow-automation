import assert from "node:assert/strict";
import test from "node:test";
import { unstable_getResponseFromNextConfig, getRedirectUrl } from "next/experimental/testing/server";
import nextConfig from "../next.config";
import { redirectUri, logoutRedirectUri } from "../lib/auth-client";

test("localhost is normalized before authentication starts, preserving the requested path", async () => {
  for (const path of ["/", "/callback?check=1"]) {
    const response = await unstable_getResponseFromNextConfig({
      url: `http://localhost:4186${path}`, headers: { host: "localhost:4186" }, nextConfig,
    });
    assert.equal(response.status, 307);
    // Next's experimental helper drops destination ports; verify the port in
    // the configured target here and against the running server during acceptance.
    const destination = new URL(getRedirectUrl(response)!);
    assert.equal(destination.hostname, "127.0.0.1");
    assert.equal(destination.pathname + destination.search, path);
  }
  const redirects = await nextConfig.redirects!();
  assert.equal(redirects[0].destination, "http://127.0.0.1:4186/:path*");
});

test("registered origin and deployed hosts do not redirect to localhost", async () => {
  for (const origin of ["http://127.0.0.1:4186", "https://marketing.example.com"]) {
    const response = await unstable_getResponseFromNextConfig({
      url: origin, headers: { host: new URL(origin).host }, nextConfig,
    });
    assert.equal(response.status, 200);
    assert.equal(getRedirectUrl(response), null);
  }
});

test("default callback and logout addresses match the registered client", () => {
  Object.defineProperty(globalThis, "window", { value: { location: { origin: "http://localhost:4186" } }, configurable: true });
  try {
    assert.equal(redirectUri(), "http://127.0.0.1:4186/callback");
    assert.equal(logoutRedirectUri(), "http://127.0.0.1:4186/");
  } finally {
    Reflect.deleteProperty(globalThis, "window");
  }
});

test("an explicit deployment callback disables the local alias redirect", async () => {
  const previous = process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI;
  process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI = "https://marketing.example.com/callback";
  try {
    assert.equal(redirectUri(), "https://marketing.example.com/callback");
    const response = await unstable_getResponseFromNextConfig({
      url: "http://localhost:4186/", headers: { host: "localhost:4186" }, nextConfig,
    });
    assert.equal(getRedirectUrl(response), null);
  } finally {
    if (previous === undefined) delete process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI;
    else process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI = previous;
  }
});
