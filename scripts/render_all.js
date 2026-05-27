#!/usr/bin/env node
/**
 * Render all caption overlays using @remotion/renderer.
 * Reads caption data JSON files prepared by render_captions.py.
 *
 * Usage:
 *   node render_all.js --data-dir captions_remotion/ --output-dir captions_remotion/
 *
 * Prerequisites (in captions_remotion/):
 *   npm install
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const args = process.argv.slice(2);
const dataDir = args[args.indexOf("--data-dir") + 1] || "./captions_remotion";
const outputDir = args[args.indexOf("--output-dir") + 1] || dataDir;

async function main() {
  // Find all caption data files
  const files = fs.readdirSync(dataDir).filter((f) => f.endsWith("_caption_data.json"));
  if (files.length === 0) {
    console.error("No caption data files found in", dataDir);
    process.exit(1);
  }

  console.log(`Found ${files.length} caption data files`);

  for (const file of files) {
    const clipId = file.replace("_caption_data.json", "");
    const dataPath = path.join(dataDir, file);
    const outputPath = path.join(outputDir, `${clipId}_captions.webm`);

    const data = JSON.parse(fs.readFileSync(dataPath, "utf-8"));
    const durationFrames = data.durationFrames || 900;

    console.log(`\nRendering clip ${clipId} (${data.events.length} events, ${durationFrames} frames)...`);

    // Write a temp composition file for this clip
    const compDir = path.join(dataDir, "src");
    if (!fs.existsSync(compDir)) fs.mkdirSync(compDir, { recursive: true });

    const compFile = path.join(dataDir, `src/ClipComp_${clipId}.tsx`);
    fs.writeFileSync(
      compFile,
      [
        `import React from 'react';`,
        `import { Composition } from 'remotion';`,
        `import { CaptionsComposition } from './CaptionsComposition';`,
        `import data from './caption_data_${clipId}.json';`,
        ``,
        `export const RemotionRoot: React.FC = () => {`,
        `  return (`,
        `    <Composition`,
        `      id="CaptionsComp_${clipId}"`,
        `      component={CaptionsComposition}`,
        `      durationInFrames={${durationFrames}}`,
        `      fps={30}`,
        `      width={1080}`,
        `      height={1920}`,
        `      defaultProps={{`,
        `        events: data.events,`,
        `        style: data.style,`,
        `        styleSlug: data.styleSlug,`,
        `      }}`,
        `    />`,
        `  );`,
        `};`,
      ].join("\n")
    );

    // Write the caption data as a JS module for import
    const dataModule = path.join(dataDir, `src/caption_data_${clipId}.json`);
    fs.copyFileSync(dataPath, dataModule);

    // Use Remotion CLI to render
    try {
      execSync(
        [
          "npx",
          "remotion",
          "render",
          ".",
          `CaptionsComp_${clipId}`,
          `--output="${outputPath}"`,
          "--codec=vp8",
          "--image-format=png",
          "--concurrency=1",
          `--frames=0-${durationFrames}`,
        ].join(" "),
        {
          cwd: dataDir,
          stdio: "inherit",
          timeout: 600000,
        }
      );
      console.log(`Rendered: ${outputPath}`);
    } catch (err) {
      console.error(`Failed to render clip ${clipId}: ${err.message}`);
      // Continue with next clip
    }
  }

  console.log(`\nAll caption overlays rendered to ${outputDir}`);
}

main().catch(console.error);
