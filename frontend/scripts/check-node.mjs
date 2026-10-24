// SPDX-License-Identifier: GPL-3.0-or-later
import { pathToFileURL } from "node:url";

export function supportedNode(version) {
  if (!/^\d+\.\d+\.\d+$/.test(version)) return false;
  const [major, minor, patch] = version.split(".").map(Number);
  const floors = { 22: [23, 4], 24: [22, 1], 26: [12, 1] };
  const floor = floors[major];
  return Boolean(floor && (minor > floor[0] || (minor === floor[0] && patch >= floor[1])));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!supportedNode(process.versions.node)) {
    console.error("Karapincho requires patched Node.js: 22.23.4+, 24.22.1+, or 26.12.1+ within those release lines. Upgrade Node and try again.");
    process.exitCode = 1;
  }
}
