import coverUrl from "../../assets/hero.png";

/**
 * Purpose:
 * Provides one realistic mock AI DJ session for frontend development.
 *
 * How this connects to the project:
 * The backend/model is not connected yet, but the UI still needs realistic data
 * to render the player, now-playing metadata, and optional AI reasoning panel.
 *
 * Engineering decision:
 * The mock follows the same DJSession type expected from the future backend.
 * This lets us replace this file with API responses later without rewriting the
 * visual components.
 *
 * Note about the cover image:
 * We import an image from src/assets so Vite bundles it correctly. This avoids a
 * broken /demo-cover.jpg path when no public image exists yet.
 *
 * @type {import("../types.js").DJSession}
 */
export const mockSession = {
  id: "session_001",
  prompt: "Start an emotional tarab-style Arabic vibe with strong vocal peaks and smooth transitions.",
  nowPlaying: {
    title: "Demo Song 1",
    artist: "Demo Artist",
    album: "Smart DJ Demo Catalog",
    coverUrl,
    vibeLabel: "Emotional Tarab Flow",
    role: "Warm intro"
  },
  reasoning: {
    selectedBecause:
      "The AI DJ chose this song moment because it has a clean emotional opening and matches the requested vocal tarab vibe.",
    transitionPlan:
      "The next transition will stay smooth and avoid sudden energy jumps, so the vibe feels continuous.",
    nextDirection:
      "The session will gradually move toward a stronger emotional vocal peak."
  }
};
