<script>
  /**
   * Fixed AI DJ control deck.
   *
   * This is not a normal Spotify-style track switcher. Zonix plays a continuous
   * AI-planned flow, so the controls focus on play/pause, stopping the session,
   * and coaching the next moments of the vibe.
   */

  import { APP_STATES } from "$lib/constants/appStates.js";

  const COACH_OPTIONS = ["Good vibe", "More energy", "Less vocals", "Smoother"];

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
   *   selectedFeedback?: string | null,
   *   onTogglePlay?: () => void,
   *   onStop?: () => void,
   *   onFeedback?: (feedback: string) => void
   * }}
   */
  let {
    status = APP_STATES.IDLE,
    currentStep = "",
    progress = 0,
    session = null,
    isPlaying = false,
    selectedFeedback = null,
    onTogglePlay = () => {},
    onStop = () => {},
    onFeedback = () => {}
  } = $props();

  let nowPlaying = $derived(session?.nowPlaying);
  let canControl = $derived(status === APP_STATES.PLAYING || status === APP_STATES.BUFFERING_NEXT);
  let isStarting = $derived(status === APP_STATES.STARTING);
  let volume = $state(72);

  /** @param {Event} event */
  function handleVolumeInput(event) {
    const target = /** @type {HTMLInputElement} */ (event.currentTarget);
    volume = Number(target.value);
  }
</script>

<section class="player-deck" aria-label="Zonix AI DJ player">
  <div class="track-block">
    {#if nowPlaying}
      <img class="cover" src={nowPlaying.coverUrl} alt={`Cover for ${nowPlaying.title}`} />
      <div class="track-copy">
        <h2>{nowPlaying.title}</h2>
        <p>{nowPlaying.artist}</p>
      </div>
      <button class="icon-button" aria-label="Save vibe">♡</button>
    {:else}
      <div class="cover placeholder">ZX</div>
      <div class="track-copy">
        <h2>Zonix is ready</h2>
        <p>Start a vibe to begin the flow.</p>
      </div>
    {/if}
  </div>

  <div class="flow-block">
    <div class="flow-status">
      <span class="signal" aria-hidden="true"></span>
      <div>
        <p class="eyebrow">
          {#if isStarting}
            Starting AI DJ
          {:else if canControl}
            AI DJ is playing...
          {:else if status === APP_STATES.STOPPED}
            Session stopped
          {:else}
            Waiting for a vibe
          {/if}
        </p>
        <p class="flow-line">
          {#if isStarting}
            {currentStep || "Preparing the first flow"}
          {:else if canControl}
            Building your mix · Smooth and emotional
          {:else if status === APP_STATES.ERROR}
            Signal interrupted
          {:else}
            Describe your vibe above.
          {/if}
        </p>
      </div>
    </div>

    <div class="deck-controls">
      <button class="play-button" onclick={onTogglePlay} disabled={!canControl} aria-label="Play or pause AI DJ">
        {isPlaying ? "Ⅱ" : "▶"}
      </button>
      <button class="stop-button" onclick={onStop} disabled={!canControl}>Stop AI DJ</button>
    </div>

    <div class="progress-line" aria-label="Current flow progress">
      <span>1:24</span>
      <div class="progress-track">
        <div class="progress-fill" style={`width: ${isStarting ? progress : 46}%`}></div>
      </div>
      <span>3:45</span>
    </div>
  </div>

  <div class="coach-block">
    <p class="eyebrow">Coach the DJ</p>
    <div class="coach-row">
      {#each COACH_OPTIONS as option}
        <button
          class:active={selectedFeedback === option}
          onclick={() => onFeedback(option)}
          disabled={!canControl}
        >
          {option}
        </button>
      {/each}
    </div>

    <div class="volume-control" aria-label="Volume control">
      <span aria-hidden="true">🔊</span>
      <input
        type="range"
        min="0"
        max="100"
        value={volume}
        oninput={handleVolumeInput}
        aria-label="Volume"
      />
      <span class="volume-value">{volume}%</span>
    </div>

    <p class="coach-note">The more you guide, the better your flow.</p>
  </div>
</section>

<style>
  .player-deck {
    position: fixed;
    left: 50%;
    bottom: 18px;
    z-index: 40;
    width: min(1500px, calc(100% - 32px));
    transform: translateX(-50%);
    display: grid;
    grid-template-columns: 330px 1fr 570px;
    gap: 26px;
    align-items: center;
    padding: 18px 24px;
    border: 1px solid rgba(125, 183, 255, 0.2);
    border-radius: 24px;
    background:
      linear-gradient(180deg, rgba(8, 16, 31, 0.94), rgba(4, 9, 18, 0.94)),
      rgba(3, 8, 16, 0.96);
    box-shadow: 0 22px 90px rgba(0, 0, 0, 0.62), 0 0 70px rgba(59, 130, 246, 0.12);
    backdrop-filter: blur(18px);
  }

  .track-block,
  .flow-status,
  .deck-controls,
  .progress-line,
  .coach-row {
    display: flex;
    align-items: center;
  }

  .track-block {
    gap: 16px;
    min-width: 0;
  }

  .cover {
    width: 70px;
    height: 70px;
    flex: 0 0 auto;
    border-radius: 14px;
    object-fit: cover;
    border: 1px solid rgba(125, 183, 255, 0.2);
  }

  .placeholder {
    display: grid;
    place-items: center;
    color: white;
    background: linear-gradient(135deg, #264984, #6ea9ff);
    font-weight: 1000;
    letter-spacing: 0.08em;
  }

  .track-copy {
    min-width: 0;
  }

  .track-copy h2 {
    overflow: hidden;
    margin: 0 0 5px;
    color: var(--text-main);
    font-size: 18px;
    font-weight: 900;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .track-copy p,
  .flow-line,
  .coach-note {
    margin: 0;
    color: var(--text-muted);
    font-size: 14px;
  }

  .icon-button {
    margin-left: auto;
    border: none;
    color: var(--text-soft);
    background: transparent;
    font-size: 28px;
  }

  .flow-block {
    display: grid;
    gap: 14px;
  }

  .flow-status {
    gap: 12px;
  }

  .signal {
    width: 26px;
    height: 18px;
    background:
      linear-gradient(90deg, transparent 0 3px, var(--accent-2) 3px 5px, transparent 5px 9px, var(--accent-2) 9px 11px, transparent 11px 16px, var(--accent-2) 16px 18px, transparent 18px);
    opacity: 0.85;
  }

  .eyebrow {
    margin: 0 0 4px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  .deck-controls {
    justify-content: center;
    gap: 18px;
  }

  .play-button {
    width: 68px;
    height: 68px;
    border: 1px solid rgba(125, 183, 255, 0.28);
    border-radius: 999px;
    display: grid;
    place-items: center;
    color: white;
    background: linear-gradient(135deg, #1f5edb, #74adff);
    box-shadow: var(--shadow-blue);
    font-size: 26px;
    font-weight: 900;
  }

  .stop-button {
    border: 1px solid rgba(125, 183, 255, 0.2);
    border-radius: 999px;
    padding: 10px 15px;
    color: var(--text-soft);
    background: rgba(125, 183, 255, 0.04);
    font-size: 13px;
    font-weight: 850;
  }

  .progress-line {
    gap: 12px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .progress-track {
    height: 6px;
    flex: 1;
    overflow: hidden;
    border-radius: 999px;
    background: rgba(125, 183, 255, 0.1);
  }

  .progress-fill {
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, #4b8cff, #7db7ff);
    transition: width 0.28s ease;
  }

  .coach-block {
    display: grid;
    gap: 10px;
  }

  .coach-row {
    flex-wrap: wrap;
    gap: 10px;
  }

  .volume-control {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 10px;
    align-items: center;
    margin-top: 2px;
    color: var(--text-soft);
    font-size: 13px;
  }

  .volume-control input[type="range"] {
    width: 100%;
    height: 5px;
    accent-color: var(--accent-2);
    cursor: pointer;
  }

  .volume-value {
    min-width: 38px;
    color: var(--text-muted);
    text-align: right;
  }

  .coach-row button {
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 10px 14px;
    color: var(--text-soft);
    background: rgba(255, 255, 255, 0.025);
    font-size: 13px;
    font-weight: 850;
  }

  .coach-row button.active,
  .coach-row button:hover:not(:disabled) {
    border-color: var(--accent-2);
    color: white;
    background: rgba(59, 130, 246, 0.16);
  }

  button:disabled {
    opacity: 0.42;
    cursor: not-allowed;
  }

  @media (max-width: 1180px) {
    .player-deck {
      grid-template-columns: 1fr;
      gap: 18px;
      position: static;
      width: 100%;
      transform: none;
      margin-top: 24px;
    }
  }

  @media (max-width: 620px) {
    .player-deck {
      padding: 16px;
    }

    .deck-controls {
      justify-content: flex-start;
    }

    .coach-row button,
    .stop-button {
      flex: 1;
    }
  }
</style>
