/** The iOS half of the LAN-cleartext policy — the ATS/Local-Network config.
 *
 * The phone reaches the self-hosted Brain over plain HTTP on the owner's LAN
 * (http://<lan-ip|.local>:7777). iOS's App Transport Security blocks cleartext
 * http:// by default — INCLUDING to private/`.local`/IP-literal hosts — so the
 * direct-LAN path is dead on iOS without an ATS exception, and the app would be
 * forced onto the HTTPS relay for every call. NSAllowsLocalNetworking is the
 * surgical exception (local resources only, NOT arbitrary internet cleartext);
 * NSLocalNetworkUsageDescription covers the iOS 14+ local-network permission.
 *
 * This mirrors the Android guarantee (plugins/withAndroidLanCleartext.js +
 * scripts/audit-android-permissions.mjs). Config lives in app.json, so pin it
 * here so a well-meaning edit that drops the exception — or widens it to a
 * blanket arbitrary-loads — fails loudly instead of silently killing LAN on iOS. */
import fs from "fs";
import path from "path";

type Ats = {
  NSAllowsLocalNetworking?: boolean;
  NSAllowsArbitraryLoads?: boolean;
  NSAllowsArbitraryLoadsInWebContent?: boolean;
  NSAllowsArbitraryLoadsForMedia?: boolean;
  [k: string]: unknown;
};

const appJson = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../app.json"), "utf8")
) as { expo: { ios: { infoPlist?: Record<string, unknown> } } };

const infoPlist = appJson.expo.ios.infoPlist ?? {};
const ats = (infoPlist.NSAppTransportSecurity ?? {}) as Ats;

describe("iOS App Transport Security — the LAN cleartext exception", () => {
  it("declares NSAppTransportSecurity with NSAllowsLocalNetworking on", () => {
    expect(ats.NSAllowsLocalNetworking).toBe(true);
  });

  it("does NOT open a blanket arbitrary-loads hole", () => {
    // NSAllowsLocalNetworking is the whole point: exempt local resources, keep
    // ATS (HTTPS-required + cert trust) enforced for every off-LAN connection.
    expect(ats.NSAllowsArbitraryLoads).not.toBe(true);
    expect(ats.NSAllowsArbitraryLoadsInWebContent).not.toBe(true);
    expect(ats.NSAllowsArbitraryLoadsForMedia).not.toBe(true);
  });
});

describe("iOS 14+ local-network permission", () => {
  it("carries a non-empty NSLocalNetworkUsageDescription", () => {
    const desc = infoPlist.NSLocalNetworkUsageDescription;
    expect(typeof desc).toBe("string");
    expect((desc as string).trim().length).toBeGreaterThan(0);
  });
});
