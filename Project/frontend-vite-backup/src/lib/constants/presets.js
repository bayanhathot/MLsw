/**
 * Purpose:
 * Stores the quick vibe presets shown under the prompt box.
 *
 * How this connects to the project:
 * Not every user knows how to write a good AI DJ prompt. Presets help users
 * start quickly, while still filling the prompt box so they can edit before
 * starting the AI DJ.
 *
 * Engineering decision:
 * Preset content is separated from UI logic. Designers/product teammates can
 * change labels and prompt wording here without editing PromptComposer.svelte.
 *
 * @type {import("../types.js").Preset[]}
 */
export const PRESETS = [
  {
    label: "Gym Energy",
    prompt: "Start a high-energy gym vibe with strong beats, clean transitions, and motivating momentum."
  },
  {
    label: "Tarab",
    prompt: "Start an emotional tarab-style Arabic vibe with strong vocal peaks and smooth transitions."
  },
  {
    label: "Chill",
    prompt: "Start a calm chill vibe with soft energy, warm sound, and relaxed transitions."
  },
  {
    label: "Party",
    prompt: "Start a party vibe with high energy, catchy moments, and smooth exciting transitions."
  },
  {
    label: "Focus",
    prompt: "Start a focus vibe with steady energy, fewer vocals, and a smooth continuous flow."
  },
  {
    label: "Classic Arabic",
    prompt: "Start a classic Arabic vibe with emotional vocals, elegant build ups, and smooth musical flow."
  },
  {
    label: "Late Night",
    prompt: "Start a late-night smooth vibe with warm sound, emotional flow, and gentle transitions."
  }
];
