// Extension: update-gallery
// One-command gallery publisher for Lavinia Enache's portfolio.
// Handles git sync (pull/rebase/conflicts), image optimization, manifest
// generation, validation, commit, and push — all transparently.

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
        const imgs   = lines.filter(l => /\.(gif|jpg|jpeg|png|webp)$/i.test(l));
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
                "use the `publish_gallery` tool — it handles everything (sync, " +
                "optimize, commit, push) in one step without needing git knowledge.",
        }),
    },

    tools: [
        {
            name: "publish_gallery",
            description:
                "Publish Lavinia's portfolio to GitHub Pages in one step. " +
                "Syncs with GitHub (pull/rebase), processes new images " +
                "(resize, watermark, thumbnail), regenerates the manifest, " +
                "validates everything, commits, and pushes. " +
                "Use this whenever the artist adds images or wants to update the site.",
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
                const cwd  = process.cwd();
                const log  = [];

                // ── 1. Sync with remote ──────────────────────────────────────
                await session.log("📥 Syncing with GitHub…", { ephemeral: true });
                try {
                    const out = await run("git pull --rebase --autostash", cwd);
                    const summary = out.split("\n").find(l =>
                        /up.to.date|rewinding|fast.forward|applying/i.test(l)
                    ) || out.split("\n")[0];
                    log.push(`✓ Synced  (${summary})`);
                } catch (err) {
                    // Detect conflict in output even when exit code is non-zero
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

                // ── 2. Optimize images ───────────────────────────────────────
                await session.log("🖼️  Optimizing images…", { ephemeral: true });
                let optimizerOut = "";
                try {
                    optimizerOut = await run("python optimize-images.py", cwd);
                    const processed = (optimizerOut.match(/✓\s+[^\n]+/g) || [])
                        .filter(l => !/Font|Manifest|already/i.test(l))
                        .slice(0, 8)
                        .join("\n    ");
                    log.push("✓ Images processed" + (processed ? `\n    ${processed}` : " (no new files)"));
                } catch (err) {
                    return `❌ Image optimization failed:\n${err.output || err.message}`;
                }

                // ── 3. Generate manifest ─────────────────────────────────────
                await session.log("📋 Generating manifest…", { ephemeral: true });
                try {
                    await run("python generate-manifest.py", cwd);
                    log.push("✓ Manifest updated");
                } catch (err) {
                    return `❌ Manifest generation failed:\n${err.output || err.message}`;
                }

                // ── 4. Validate ──────────────────────────────────────────────
                await session.log("✅ Validating…", { ephemeral: true });
                try {
                    await run("python validate.py", cwd);
                    log.push("✓ Validation passed");
                } catch (err) {
                    return `❌ Validation failed — nothing was committed:\n${err.output || err.message}`;
                }

                // ── 5. Check for changes ─────────────────────────────────────
                let status = "";
                try {
                    status = await run("git status --porcelain", cwd);
                } catch (err) {
                    return `❌ Could not check git status:\n${err.output || err.message}`;
                }

                if (!status.trim()) {
                    return `✅ Everything is already up to date — nothing to publish.\n\n${log.join("\n")}`;
                }

                // ── 6. Commit ────────────────────────────────────────────────
                await session.log("💾 Committing…", { ephemeral: true });
                try {
                    const msg = args.commit_message || await buildCommitMessage(cwd);
                    const safeMsg = msg.replace(/"/g, '\\"').replace(/`/g, "'");
                    await run("git add -A", cwd);
                    await run(`git commit -m "${safeMsg}"`, cwd);
                    log.push(`✓ Committed: "${msg}"`);
                } catch (err) {
                    return `❌ Commit failed:\n${err.output || err.message}`;
                }

                // ── 7. Push ──────────────────────────────────────────────────
                await session.log("🚀 Pushing to GitHub Pages…", { ephemeral: true });
                try {
                    await run("git push", cwd);
                    log.push("✓ Live on laviniaenache.com  (GitHub Pages deploys in ~1 min)");
                } catch (err) {
                    return `❌ Push failed:\n${err.output || err.message}`;
                }

                return `🎨 Gallery published!\n\n${log.join("\n")}`;
            },
        },
    ],
});
