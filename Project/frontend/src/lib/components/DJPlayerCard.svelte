<script>
  /*
    Main AI DJ player card.

    Design goal:
    - Compact horizontal music-player style.
    - Similar to the older version.
    - Shows cover, title, artist, album, play/pause, progress bar, and stop button.
  */

  import { APP_STATES } from "$lib/constants/appStates.js";

  /**
   * @typedef {import("$lib/types.js").AppStatus} AppStatus
   * @typedef {import("$lib/types.js").Session} Session
   */

  /**
   * @type {{
   *   status?: AppStatus,
   *   currentStep?: string,
   *   progress?: number,
   *   session?: Session | null,
   *   isPlaying?: boolean,
   *   onTogglePlay?: () => void,
   *   onStop?: () => void
   * }}
   */
  let {
    status = APP_STATES.IDLE,
    currentStep = "",
    progress = 0,
    session = null,
    isPlaying = false,
    onTogglePlay = () => {},
    onStop = () => {}
  } = $props();

  let nowPlaying = $derived(session?.nowPlaying);
</script>

<section class="player-card card">
  {#if status === APP_STATES.IDLE}
    <div class="empty-player">
      <div class="cover-placeholder">DJ</div>

      <div>
        <p class="eyebrow">Ready when you are</p>
        <h2>Your AI DJ is waiting.</h2>
        <p>Describe the vibe below and start the session.</p>
      </div>
    </div>
  {:else if status === APP_STATES.STARTING}
    <div class="loading-player">
      <div>
        <p class="eyebrow">Starting AI DJ</p>
        <h2>{currentStep}</h2>
      </div>

      <div class="progress-area">
        <div class="progress-track">
          <div class="progress-fill" style={`width: ${progress}%`}></div>
        </div>
        <span>{progress}%</span>
      </div>
    </div>
  {:else if status === APP_STATES.PLAYING && nowPlaying}
    <div class="playing-player">
      <div class="track-left">
        <img
          class="cover"
          src={nowPlaying.coverUrl}
          alt={`Cover for ${nowPlaying.title}`}
        />

        <div>
          <p class="eyebrow">{nowPlaying.vibeLabel}</p>
          <h2>{nowPlaying.title}</h2>
          <p class="artist">{nowPlaying.artist}</p>
          <p class="album">{nowPlaying.album}</p>
        </div>
      </div>

      <div class="center-controls">
        <button class="play-button" onclick={onTogglePlay}>
          {isPlaying ? "Ⅱ" : "▶"}
        </button>

        <div class="mini-timeline">
          <span>0:35</span>

          <div class="timeline-track">
            <div class="timeline-fill"></div>
          </div>

          <span>2:56</span>
        </div>
      </div>

      <div class="right-controls">
        <span class="mood-chip">Warm intro</span>

        <button class="secondary-button" onclick={onStop}>
          Stop AI DJ
        </button>
      </div>
    </div>
  {:else if status === APP_STATES.STOPPED && nowPlaying}
    <div class="stopped-player">
      <div class="track-left">
        <img
          class="cover"
          src={nowPlaying.coverUrl}
          alt={`Cover for ${nowPlaying.title}`}
        />

        <div>
          <p class="eyebrow">Session stopped</p>
          <h2>{nowPlaying.title}</h2>
          <p class="artist">{nowPlaying.artist}</p>
          <p>Start a new vibe below when you are ready.</p>
        </div>
      </div>

      <p class="stopped-note">
        The AI DJ is stopped. For MVP we do not resume stopped sessions; start a
        new prompt to begin another vibe.
      </p>
    </div>
  {:else if status === APP_STATES.ERROR}
    <div class="empty-player">
      <div class="cover-placeholder">!</div>

      <div>
        <p class="eyebrow">Error</p>
        <h2>The player could not start.</h2>
        <p>Please try again.</p>
      </div>
    </div>
  {/if}
</section>

<style>
  .player-card {
    padding: 24px;
    margin: 34px 0 22px;
  }

  .empty-player,
  .loading-player,
  .playing-player,
  .stopped-player {
    display: grid;
    gap: 24px;
    align-items: center;
  }

  .playing-player {
    grid-template-columns: 1.4fr 1fr auto;
  }

  .stopped-player {
    grid-template-columns: 1fr 1.1fr;
  }

  .track-left {
    display: flex;
    align-items: center;
    gap: 18px;
    min-width: 0;
  }

  .cover,
  .cover-placeholder {
    width: 88px;
    height: 88px;
    flex: 0 0 auto;
    border-radius: 22px;
  }

  .cover {
    object-fit: cover;
    box-shadow: var(--shadow-soft);
  }

  .cover-placeholder {
    display: grid;
    place-items: center;
    font-weight: 900;
    color: white;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
  }

  .eyebrow {
    margin: 0 0 6px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  h2 {
    margin: 0;
    font-size: clamp(26px, 3vw, 38px);
    line-height: 1.05;
  }

  .artist {
    margin: 8px 0 0;
    color: var(--text-main);
    font-weight: 800;
  }

  .album,
  p {
    margin: 6px 0 0;
    color: var(--text-muted);
  }

  .center-controls {
    display: grid;
    gap: 14px;
    justify-items: center;
  }

  .play-button {
    width: 58px;
    height: 58px;
    border: none;
    border-radius: 999px;
    display: grid;
    place-items: center;
    color: #111827;
    background: white;
    font-size: 24px;
    font-weight: 900;
    cursor: pointer;
  }

  .mini-timeline {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 12px;
    align-items: center;
    color: var(--text-muted);
    font-size: 13px;
  }

  .timeline-track,
  .progress-track {
    height: 7px;
    overflow: hidden;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.12);
  }

  .timeline-fill {
    width: 36%;
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
  }

  .progress-area {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 14px;
    align-items: center;
  }

  .progress-fill {
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    transition: width 0.25s ease;
  }

  .right-controls {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .mood-chip {
    border-radius: 999px;
    padding: 9px 12px;
    color: var(--text-muted);
    background: rgba(255, 255, 255, 0.08);
    font-size: 13px;
    font-weight: 800;
  }

  .stopped-note {
    max-width: 580px;
    line-height: 1.7;
  }

  @media (max-width: 980px) {
    .playing-player,
    .stopped-player {
      grid-template-columns: 1fr;
    }

    .center-controls {
      justify-items: stretch;
    }

    .right-controls {
      justify-content: space-between;
    }
  }

  @media (max-width: 640px) {
    .track-left {
      align-items: flex-start;
    }

    .cover,
    .cover-placeholder {
      width: 72px;
      height: 72px;
      border-radius: 18px;
    }

    .right-controls {
      flex-direction: column;
      align-items: stretch;
    }
  }
</style>