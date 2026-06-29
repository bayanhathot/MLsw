/**
 * File: src/lib/constants/presets.js
 * Purpose: Quick vibe presets shown in the prompt composer.
 * What it does:
 * - Stores user-facing preset labels.
 * - Stores the longer prompt text each label inserts into the prompt box.
 * - Keeps preset data separate from UI components so it is easy to edit later.
 * Future use:
 * - These can later be replaced by backend recommendations, user recent prompts, or saved zones.
 */

/**
 * Prompt shortcuts for the MVP.
 * They are intentionally text-only so this section can later become recent
 * prompts, saved vibes, or personalized suggestions.
 *
 * @type {import("../types.js").Preset[]}
 */
export const PRESETS = [
  {
    label: "deep work focus",
    prompt: "Create a deep work focus mix with clean, steady, low-distraction flow and smooth transitions."
  },
  {
    label: "late night coding",
    prompt: "Create a late night coding mix with lo-fi calm, smooth transitions, and low vocal distraction."
  },
  {
    label: "emotional Arabic vocals",
    prompt: "Create an emotional Arabic vocal flow with warm vocals, nostalgic moments, and smooth transitions."
  },
  {
    label: "gym energy",
    prompt: "Create a gym energy mix with driving rhythm, momentum, and no sudden drops."
  },
  {
    label: "chill and relax",
    prompt: "Create a chill relaxing flow with soft slower energy and easy listening transitions."
  },
  {
    label: "party warmup",
    prompt: "Create a party warmup mix that is upbeat but not too intense, with clean energy build-up."
  }
];
