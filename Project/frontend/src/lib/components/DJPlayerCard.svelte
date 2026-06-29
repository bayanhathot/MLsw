<script>
  import { APP_STATES } from "../constants/appStates.js";

  /**
   * Purpose:
   * Main user-facing AI DJ player.
   *
   * How this connects to the project:
   * This replaces the technical timeline/score dashboard in the normal user flow.
   * It shows what the user actually cares about: current song, artist, album/source,
   * cover image, vibe label, playback controls, and stop action.
   *
   * Engineering decisions:
   * - Raw ML details such as mix score, segment score, and timestamps are hidden.
   * - Previous/next buttons were removed for MVP because there is no real queue yet.
   * - Stopped state is separate from playing state to avoid "stopped but playing" bugs.
   *
   * @typedef {import("../types.js").AppStatus} AppStatus
   * @typedef {import("../types.js").DJSession} DJSession
   */

  /** @type {AppStatus} */
  export let status = APP_STATES.IDLE;

  /** @type {string} */
  export let currentStep = "";

  /** @type {number} */
  export let progress = 0;

  /** @type {DJSession | null} */
  export let session = null;

  /** @type {boolean} */
  export let isPlaying = false;

  /** @type {() => void} */
  export let onTogglePlay = () => {};

  /** @type {() => void} */
  export let onStop = () => {};
</script>

<section class="player-card card">
  {#if status === APP_STATES.IDLE}
    <div class="idle-visual" aria-hidden="true">
      <div class="disc"></div>
    </div>

    <div class="content wide">
      <p class="eyebrow">AI DJ is ready</p>
      <h2>Describe a vibe and start listening.</h2>
      <p class="muted">The session will keep mixing until you stop it.</p>
    </div>
  {:else if status === APP_STATES.STARTING}
    <div class="idle-visual" aria-hidden="true">
      <div class="disc spinning"></div>
    </div>

    <div class="content wide">
      <p class="eyebrow">Starting AI DJ</p>
      <h2>{currentStep}</h2>

      <div class="progress-track" aria-label="AI DJ startup progress">
        <div class="progress-fill" style={`width: ${progress}%`}></div>
      </div>

      <p class="muted">{progress}% ready</p>
    </div>
  {:else if (status === APP_STATES.PLAYING || status === APP_STATES.BUFFERING_NEXT) && session}
    <div class="track-info">
      <img
        class="cover"
        src={session.nowPlaying.coverUrl}
        alt={`Cover art for ${session.nowPlaying.title}`}
      />

      <div class="track-copy">
        <p class="eyebrow">{session.nowPlaying.vibeLabel}</p>
        <h2>{session.nowPlaying.title}</h2>
        <p class="artist">{session.nowPlaying.artist}</p>
        <p class="muted">{session.nowPlaying.album}</p>
      </div>
    </div>

    <div class="player-controls">
      <button class="play-button" on:click={onTogglePlay} aria-label="Play or pause">
        {isPlaying ? "⏸" : "▶"}
      </button>

      <div class="progress-row" aria-label="Mock playback progress">
        <span>0:35</span>
        <div class="playback-track">
          <div class="playback-fill"></div>
        </div>
        <span>2:56</span>
      </div>

      {#if status === APP_STATES.BUFFERING_NEXT}
        <p class="buffering-note">Preparing the next transition...</p>
      {/if}
    </div>

    <div class="session-actions">
      <span class="badge">{session.nowPlaying.role}</span>
      <button class="secondary-button" on:click={onStop}>Stop AI DJ</button>
    </div>
  {:else if status === APP_STATES.STOPPED && session}
    <div class="track-info">
      <img
        class="cover"
        src={session.nowPlaying.coverUrl}
        alt={`Cover art for ${session.nowPlaying.title}`}
      />

      <div class="track-copy">
        <p class="eyebrow stopped">Session stopped</p>
        <h2>{session.nowPlaying.title}</h2>
        <p class="artist">{session.nowPlaying.artist}</p>
        <p class="muted">Start a new vibe below when you are ready.</p>
      </div>
    </div>

    <div class="content wide">
      <p class="muted">
        The AI DJ is stopped. For MVP we do not resume stopped sessions; start a
        new prompt to begin another vibe.
      </p>
    </div>
  {:else if status === APP_STATES.ERROR}
    <div class="content full">
      <p class="eyebrow error">Session failed</p>
      <h2>Try another vibe or choose a preset.</h2>
    </div>
  {/if}
</section>

<style>
  .player-card {
    display: grid;
    grid-template-columns: 1.2fr 1.4fr 0.9fr;
    align-items: center;
    gap: 24px;
    padding: 24px;
    margin-bottom: 24px;
    min-height: 170px;
  }

  .idle-visual {
    min-height: 150px;
    border-radius: 22px;
    background:
      radial-gradient(circle at center, rgba(139, 92, 246, 0.35), transparent 45%),
      rgba(255, 255, 255, 0.06);
    display: grid;
    place-items: center;
    overflow: hidden;
  }

  .disc {
    width: 98px;
    height: 98px;
    border-radius: 50%;
    border: 20px solid rgba(255, 255, 255, 0.12);
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
  }

  .spinning {
    animation: spin 2s linear infinite;
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  .track-info {
    display: flex;
    align-items: center;
    gap: 16px;
    min-width: 0;
  }

  .cover {
    width: 92px;
    height: 92px;
    border-radius: 22px;
    object-fit: cover;
    background: rgba(255, 255, 255, 0.1);
  }

  .track-copy {
    min-width: 0;
  }

  .content.wide {
    grid-column: span 2;
  }

  .content.full {
    grid-column: 1 / -1;
  }

  .eyebrow {
    margin: 0 0 8px;
    color: var(--accent-2);
    font-weight: 800;
    text-transform: uppercase;
    font-size: 12px;
    letter-spacing: 0.14em;
  }

  .error {
    color: var(--danger);
  }

  .stopped {
    color: var(--text-muted);
  }

  h2 {
    margin: 0 0 8px;
    font-size: clamp(24px, 3vw, 36px);
    line-height: 1.05;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .artist {
    margin: 0 0 4px;
    font-weight: 700;
  }

  .muted {
    margin: 0;
    color: var(--text-muted);
    line-height: 1.6;
  }

  .progress-track,
  .playback-track {
    height: 8px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.12);
    overflow: hidden;
  }

  .progress-fill,
  .playback-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
  }

  .playback-fill {
    width: 35%;
  }

  .player-controls {
    display: flex;
    flex-direction: column;
    gap: 12px;
    align-items: center;
  }

  .play-button {
    border: none;
    width: 54px;
    height: 54px;
    border-radius: 999px;
    background: white;
    color: #111827;
    font-size: 20px;
    font-weight: 900;
  }

  .progress-row {
    width: 100%;
    display: grid;
    grid-template-columns: 42px 1fr 42px;
    align-items: center;
    gap: 10px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .buffering-note {
    margin: 0;
    color: var(--accent-2);
    font-size: 13px;
    font-weight: 700;
  }

  .session-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  @media (max-width: 900px) {
    .player-card {
      grid-template-columns: 1fr;
    }

    .content.wide,
    .content.full {
      grid-column: auto;
    }

    .session-actions {
      justify-content: flex-start;
    }
  }
</style>
