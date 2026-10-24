// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import test from "node:test";
import { supportedNode } from "./check-node.mjs";

test("rejects vulnerable, EOL, prerelease, and unreviewed Node releases", () => {
  for (const version of ["20.20.0", "22.23.3", "24.22.0", "26.10.0", "26.12.0", "23.0.0", "25.0.0", "27.0.0", "26.12.1-rc.1", "invalid"]) {
    assert.equal(supportedNode(version), false, version);
  }
});

test("accepts the October security fixes and subsequent patches in supported lines", () => {
  for (const version of ["22.23.4", "24.22.1", "26.12.1", "22.24.0", "24.23.0", "26.12.2"]) {
    assert.equal(supportedNode(version), true, version);
  }
});
