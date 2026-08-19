/**
 * agentic-meta plugin for OpenCode.
 *
 * Registers skills/ via config.skills.paths, and does nothing else.
 *
 * Only skills/ is registered. The synthetic trees under .fixtures/ also hold
 * SKILL.md files, but they are targets these skills measure rather than skills
 * a session should be able to invoke; registering them would put deliberately
 * malformed skills into the runtime that is meant to inspect them.
 */

import path from "path"
import { fileURLToPath } from "url"

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const SKILLS_DIR = path.join(PACKAGE_ROOT, "skills")

const AgenticMetaPlugin = async () => {
  return {
    config: async (config) => {
      config.skills = config.skills || {}
      config.skills.paths = config.skills.paths || []
      if (!config.skills.paths.includes(SKILLS_DIR)) {
        config.skills.paths.push(SKILLS_DIR)
      }
    },
  }
}

// OpenCode treats every module export as a plugin, so the plugin function is
// this module's only export.
export default AgenticMetaPlugin
