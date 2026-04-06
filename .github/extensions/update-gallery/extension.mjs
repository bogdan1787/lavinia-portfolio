// Extension: update-gallery
// One-command gallery publisher for Lavinia Enache's portfolio.
// Syncs with GitHub (pull/rebase), commits any local changes, and pushes.
// Image optimisation, manifest generation, and validation all run in CI
// (GitHub Actions) automatically after the push — no local tooling required.

import { execFile } from "node:child_process";
import { joinSession } from "@github/copilot-sdk/extension";

const isWindows = process.platform === "win32";

/** Run a shell command, resolve with trimmed stdout, reject with annotated error. */
function run(cmd, cwd) {
    return new Promise((resolve, reject) => {
        const shell = isWindows ? "powershell" : "bash";
        const args  = isWindows
            ? ["-NoProfile", "-NonInteractive", "-Command", cmd]
            : ["-c", cmd];
        execFile(shell, args, { cwd, maxBuffer: 20 * 1024 * 1024 }, (err, stdout, stderr) => {
            const combined = (stdout + "\n" + stderr).trim();
            if (err) {
                const wrapped = new Error(combined || err.message);
                wrapped.output = combined;
                reject(wrapped);
            } else {
                resolve(combined);
            }
        });
    });
}

/** Build a human-readable commit message from uncommitted files. */
async function buildCommitMessage(cwd) {
    try {
        const status = await run("git status --porcelain", cwd);
        const lines  = status.split("\n").filter(Boolean);
        const imgs   = lines.filter(l => /\.(gif|jpg|jpeg|png|webp|mp4)$/i.test(l));
        if (imgs.length === 0) return "Update gallery";
        if (imgs.length === 1) {
            const name = imgs[0].replace(/^.{3}/, "").trim().split(/[\\/]/).pop();
            return `Add ${name}`;
        }
        return `Update gallery: ${imgs.length} images`;
    } catch {
        return "Update gallery";
    }
}

const session = await joinSession({
    hooks: {
        onSessionStart: async () => ({
            additionalContext:
                "This is Lavinia Enache's artist portfolio (laviniaenache.com). " +
                "When the user wants to publish new artwork or update the website, " +
                "use the `publish_gallery` tool — it syncs, commits, and pushes in " +
                "one step. GitHub Actions handles image processing automatically.",
        }),
    },

    tools: [
        {
            name: "update_website",
            description:
                "Update Lavinia's portfolio website on GitHub Pages in one step. " +
                "Syncs with GitHub (pull/rebase), commits any pending changes, " +
                "and pushes. GitHub Actions then automatically optimises images " +
                "(resize, watermark, thumbnail), regenerates the manifest, and deploys. " +
                "Use this whenever the artist adds images/videos or wants to update the site.",
            skipPermission: true,
            parameters: {
                type: "object",
                properties: {
                    commit_message: {
                        type: "string",
                        description:
                            "Optional custom commit message. " +
                            "If omitted, one is generated from the changed files.",
                    },
                },
            },
            handler: async (args) => {
                const cwd = process.cwd();
                const log = [];

                // ── 1. Sync with remote ──────────────────────────────────────
                await session.log("📥 Syncing with GitHub…", { ephemeral: true });
                try {
                    const out = await run("git pull --rebase --autostash", cwd);
                    const summary = out.split("\n").find(l =>
                        /up.to.date|rewinding|fast.forward|applying/i.test(l)
                    ) || out.split("\n")[0];
                    log.push(`✓ Synced  (${summary})`);
                } catch (err) {
                    if (/CONFLICT|conflict/i.test(err.output)) {
                        return (
                            "❌ Merge conflict detected — cannot auto-resolve.\n\n" +
                            "Run `git rebase --abort` to cancel, or open the repo in\n" +
                            "VS Code and resolve the conflicts, then run `git rebase --continue`.\n\n" +
                            `Details:\n${err.output}`
                        );
                    }
                    return `❌ Sync failed:\n${err.output || err.message}`;
                }

                // ── 2. Check for changes ─────────────────────────────────────
                let status = "";
                try {
                    status = await run("git status --porcelain", cwd);
                } catch (err) {
                    return `❌ Could not check git status:\n${err.output || err.message}`;
                }

                if (!status.trim()) {
                    return `✅ Everything is already up to date — nothing to publish.\n\n${log.join("\n")}`;
                }

                // ── 3. Commit ────────────────────────────────────────────────
                await session.log("💾 Committing…", { ephemeral: true });
                try {
                    const msg     = args.commit_message || await buildCommitMessage(cwd);
                    const safeMsg = msg.replace(/"/g, '\\"').replace(/`/g, "'");
                    await run("git add -A", cwd);
                    await run(`git commit -m "${safeMsg}"`, cwd);
                    log.push(`✓ Committed: "${msg}"`);
                } catch (err) {
                    return `❌ Commit failed:\n${err.output || err.message}`;
                }

                // ── 4. Push ──────────────────────────────────────────────────
                await session.log("🚀 Pushing to GitHub…", { ephemeral: true });
                try {
                    await run("git push", cwd);
                    log.push("✓ Pushed — GitHub Actions is now optimising images & deploying\n" +
                             "  (~1–2 min until live on laviniaenache.com)");
                } catch (err) {
                    return `❌ Push failed:\n${err.output || err.message}`;
                }

                return `🎨 Gallery published!\n\n${log.join("\n")}`;
            },
        },
    ],
});
