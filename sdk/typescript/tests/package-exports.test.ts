import { spawnSync } from "node:child_process";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

type PackFile = { path: string };
type PackResult = { filename: string; files: PackFile[] };

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
let temporaryRoot = "";
let consumerRoot = "";
let npmCache = "";
let packedFiles: string[] = [];

function runProcess(
  executable: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const result = spawnSync(executable, args, {
    cwd,
    env,
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      [
        `Command failed (${result.status}): ${executable} ${args.join(" ")}`,
        result.stdout,
        result.stderr,
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  return result.stdout;
}

function npmEnvironment(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    npm_config_cache: npmCache,
    npm_config_audit: "false",
    npm_config_fund: "false",
    npm_config_update_notifier: "false",
  };
}

function runNpm(args: string[], cwd: string): string {
  const npmCli = process.env.npm_execpath;
  if (!npmCli) {
    throw new Error("npm_execpath is required for packed-artifact tests");
  }
  return runProcess(process.execPath, [npmCli, ...args], cwd, npmEnvironment());
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function runConsumer(
  fileName: string,
  source: string,
  nodeArgs: string[] = [],
): Promise<string> {
  const scriptPath = join(consumerRoot, fileName);
  await writeFile(scriptPath, source, "utf8");
  return runProcess(process.execPath, [...nodeArgs, scriptPath], consumerRoot);
}

beforeAll(async () => {
  temporaryRoot = await mkdtemp(join(tmpdir(), "chatvector-sdk-pack-"));
  npmCache = join(temporaryRoot, "npm-cache");
  consumerRoot = join(temporaryRoot, "consumer");

  if (!(await exists(join(packageRoot, "dist", "index.js")))) {
    runNpm(["run", "build"], packageRoot);
  }

  const packOutput = runNpm(
    ["pack", "--json", "--pack-destination", temporaryRoot],
    packageRoot,
  );
  const parsed = JSON.parse(packOutput) as PackResult[];
  const pack = parsed[0];
  if (!pack) throw new Error("npm pack returned no artifact");
  packedFiles = pack.files.map((file) => file.path).sort();
  const tarball = join(temporaryRoot, pack.filename);

  await writeFile(
    join(temporaryRoot, "consumer-package.json"),
    JSON.stringify({ private: true, type: "module" }),
    "utf8",
  );
  await import("node:fs/promises").then(({ mkdir }) =>
    mkdir(consumerRoot, { recursive: true }),
  );
  await writeFile(
    join(consumerRoot, "package.json"),
    JSON.stringify({ private: true, type: "module" }),
    "utf8",
  );
  runNpm(
    [
      "install",
      "--ignore-scripts",
      "--no-audit",
      "--no-fund",
      "--package-lock=false",
      tarball,
    ],
    consumerRoot,
  );
}, 120_000);

afterAll(async () => {
  if (temporaryRoot) {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
}, 30_000);

describe("packed @chatvector/sdk exports", () => {
  it("contains only the intended publishable package surface", async () => {
    expect(packedFiles).toEqual(
      expect.arrayContaining([
        "LICENSE",
        "README.md",
        "dist/browser-stub.js",
        "dist/index.cjs",
        "dist/index.d.ts",
        "dist/index.js",
        "package.json",
      ]),
    );
    expect(
      packedFiles.some((path) =>
        /^(src|tests|examples)\//.test(path.replaceAll("\\", "/")),
      ),
    ).toBe(false);
    expect(packedFiles.some((path) => path.endsWith(".tgz"))).toBe(false);

    const installedPackagePath = join(
      consumerRoot,
      "node_modules",
      "@chatvector",
      "sdk",
      "package.json",
    );
    const metadata = JSON.parse(
      await readFile(installedPackagePath, "utf8"),
    ) as Record<string, unknown>;
    expect(metadata).toMatchObject({
      name: "@chatvector/sdk",
      version: "0.1.0",
      type: "module",
      engines: { node: ">=22" },
      exports: {
        ".": {
          types: "./dist/index.d.ts",
          browser: "./dist/browser-stub.js",
          import: "./dist/index.js",
          require: "./dist/index.cjs",
        },
      },
    });
    expect(metadata.dependencies).toBeUndefined();
    expect(dirname(installedPackagePath)).toContain(
      join("node_modules", "@chatvector", "sdk"),
    );
  });

  it("supports ESM named imports from the packed artifact", async () => {
    const output = await runConsumer(
      "esm-consumer.mjs",
      `
        import assert from "node:assert/strict";
        import {
          ChatVectorClient,
          ChatVectorAPIError,
          ChatVectorAuthError,
          ChatVectorRateLimitError,
          ChatVectorTimeoutError,
          isChatVectorError,
        } from "@chatvector/sdk";
        assert.equal(typeof ChatVectorClient, "function");
        assert.equal(typeof ChatVectorAPIError, "function");
        assert.equal(typeof ChatVectorAuthError, "function");
        assert.equal(typeof ChatVectorRateLimitError, "function");
        assert.equal(typeof ChatVectorTimeoutError, "function");
        assert.equal(isChatVectorError({ kind: "api", message: "x" }), true);
        const client = new ChatVectorClient({ baseUrl: "https://api.example.test" });
        assert.equal(typeof client.chat, "function");
        assert.equal("streamChat" in client, false);
        console.log("esm-ok");
      `,
    );
    expect(output).toContain("esm-ok");
  });

  it("supports CommonJS require from the packed artifact", async () => {
    const output = await runConsumer(
      "cjs-consumer.cjs",
      `
        const assert = require("node:assert/strict");
        const sdk = require("@chatvector/sdk");
        assert.equal(typeof sdk.ChatVectorClient, "function");
        assert.equal(typeof sdk.ChatVectorAPIError, "function");
        const client = new sdk.ChatVectorClient({ baseUrl: "https://api.example.test" });
        assert.equal(typeof client.listSessions, "function");
        assert.equal(sdk.isChatVectorError({ kind: "timeout", message: "x" }), true);
        console.log("cjs-ok");
      `,
    );
    expect(output).toContain("cjs-ok");
  });

  it("selects the intentional browser stub under the browser condition", async () => {
    const output = await runConsumer(
      "browser-consumer.mjs",
      `
        import assert from "node:assert/strict";
        const sentinel = "cv_live_must_not_appear";
        try {
          await import("@chatvector/sdk");
          assert.fail("browser import unexpectedly succeeded");
        } catch (error) {
          assert.match(String(error?.message), /server-only/i);
          assert.match(String(error?.message), /browser/i);
          assert.doesNotMatch(String(error?.message), new RegExp(sentinel));
          console.log("browser-stub-ok");
        }
      `,
      ["--conditions=browser"],
    );
    expect(output).toContain("browser-stub-ok");
  });

  it("does not expose internal deep imports", async () => {
    const output = await runConsumer(
      "deep-import.mjs",
      `
        import assert from "node:assert/strict";
        try {
          await import("@chatvector/sdk/internal/http");
          assert.fail("deep import unexpectedly succeeded");
        } catch (error) {
          assert.equal(error?.code, "ERR_PACKAGE_PATH_NOT_EXPORTED");
          console.log("deep-import-blocked");
        }
      `,
    );
    expect(output).toContain("deep-import-blocked");
  });
});
