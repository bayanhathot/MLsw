/**
 * File: src/lib/data/mockSession.js
 * Purpose: Mock AI DJ session returned by the fake frontend service.
 * What it does:
 * - Provides realistic demo data before the real backend/model is connected.
 * - Describes the current track/moment, cover image, audio URL placeholder, and AI reasoning text.
 * - Lets the frontend look and behave like a product during the MVP/demo stage.
 * Important:
 * - This is demo data only. Later, FastAPI/Flask should return the same shape from a real endpoint.
 */

import coverUrl from "../../assets/hero.png";

/**
 * Mock Zonix session for frontend development.
 * Later this object should come from POST /sessions/start.
 *
 * @type {import("../types.js").Session}
 */
export const mockSession = {
  id: "zonix_session_001",
  prompt: "Create an emotional Arabic vocal flow with warm vocals, nostalgic moments, and smooth transitions.",
  vibeLabel: "Smooth emotional flow",
  audioUrl: "/audio/mock-mix.mp3",
  nowPlaying: {
    title: "Midnight Whispers",
    artist: "Hassan Al-Shafei",
    album: "Zonix Demo Catalog",
    coverUrl,
    vibeLabel: "Smooth emotional flow",
    role: "Building your mix"
  },
  reasoning: {
    selectedMoment:
      "Zonix selected this moment because the vocal energy is warm, the entry is clean, and it fits the requested emotional flow.",
    transitionPlan:
      "The next transition keeps the mood stable instead of abruptly switching songs.",
    nextDirection:
      "The mix will stay smooth while slowly increasing momentum if the user asks for more energy."
  }
};
