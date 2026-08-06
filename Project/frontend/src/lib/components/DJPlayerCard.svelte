<!--
  File: src/lib/components/DJPlayerCard.svelte

  Purpose:
  Fixed bottom AI DJ control deck for the Zonix frontend.

  What this component does:
  - Shows the currently selected AI DJ moment: cover image, title, and artist.
  - Shows the current AI DJ status: waiting, starting, playing, stopped, or error.
  - Lets the user play or pause the active session.
  - Lets the user stop the AI DJ session.
  - Shows Coach the DJ feedback buttons:
    Good vibe, More energy, Less vocals, Smoother.
  - Shows a volume slider.
  - Plays the real demo MP3 returned from the backend through session.audioUrl.

  Important product decision:
  This is not only a Spotify-style song player.
  Zonix is an AI DJ system, so this player focuses on guiding the music flow,
  not only controlling a single song.
-->

<script>
  /**
   * Fixed AI DJ control deck.
   *
   * This component receives all important session data from the parent page/store.
   * It does not create sessions by itself.
   * It only displays the active session and triggers callbacks such as:
   * - onTogglePlay()
   * - onStop()
   * - onFeedback()
   */

  import { onDestroy, onMount } from "svelte";

  import { APP_STATES } from "$lib/constants/appStates.js";
  import EqualizerBars from "$lib/components/EqualizerBars.svelte";

  /**
   * Feedback options shown in the Coach the DJ section.
   *
   * These options are sent to the backend when clicked.
   * Later, the backend can use them to choose better next segments.
   */
  const COACH_OPTIONS = ["Good vibe", "More energy", "Less vocals", "Smoother"];

  /**
   * @typedef {import("$lib/types.js").AppStatus} AppStatus
   * @typedef {import("$lib/types.js").Session} Session
   */

  /**
   * Props passed from the parent page/store.
   *
   * status:
   *   Current state of the AI DJ session.
   *
   * currentStep:
   *   Human-readable message about what the app is doing now.
   *
   * progress:
   *   Simple UI progress value used while starting/loading.
   *
   * session:
   *   Current backend session object.
   *   This contains nowPlaying metadata and audioUrl.
   *
   * isPlaying:
   *   Whether the frontend considers the session currently playing.
   *
   * selectedFeedback:
   *   The feedback option most recently selected by the user.
   *
   * onTogglePlay:
   *   Callback for play/pause button.
   *
   * onStop:
   *   Callback for Stop AI DJ button.
   *
   * onFeedback:
   *   Callback for Coach the DJ feedback buttons.
   *
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

  /**
   * Current track/segment information returned from the backend.
   *
   * Example:
   * session.nowPlaying.title
   * session.nowPlaying.artist
   * session.nowPlaying.coverUrl
   */
  let nowPlaying = $derived(session?.nowPlaying);

  /**
   * The backend audio URL.
   *
   * For the current demo, this should be:
   * http://localhost:5000/static/audio/demo.mp3
   */
  let audioUrl = $derived(session?.audioUrl || "");

  /**
   * The user can control the player only while the session is playing
   * or preparing the next segment.
   */
  let canControl = $derived(status === APP_STATES.PLAYING || status === APP_STATES.BUFFERING_NEXT);

  /**
   * True while the backend is creating the session or preparing the first moment.
   */
  let isStarting = $derived(status === APP_STATES.STARTING);

  /**
   * Frontend volume state.
   *
   * The slider value is 0-100, but the real HTMLAudioElement volume expects 0-1.
   */
  let volume = $state(72);

  /**
   * Reference to the real <audio> element.
   *
   * bind:this={audioElement} connects this variable to the DOM audio player.
   */
  /** @type {HTMLAudioElement | null} */
  let audioElement = $state(null);


  let currentTime = $state(0);
  let duration = $state(0);

  let progressPercent = $derived(
    duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0
  );

  /**
   * Drive currentTime from a requestAnimationFrame loop instead of only
   * the native `timeupdate` event, which the browser fires only a
   * handful of times per second - too coarse for a smooth-looking
   * progress bar. This runs continuously and simply no-ops while paused.
   */
  let progressFrameId = null;

  function stepProgressFrame() {
    if (audioElement && !audioElement.paused) {
      currentTime = audioElement.currentTime;
    }

    progressFrameId = requestAnimationFrame(stepProgressFrame);
  }

  onMount(() => {
    progressFrameId = requestAnimationFrame(stepProgressFrame);
  });

  onDestroy(() => {
    if (progressFrameId) {
      cancelAnimationFrame(progressFrameId);
    }
  });

  /**
   * Apply the volume slider value to the real audio element.
   *
   * Example:
   * volume = 72
   * audioElement.volume = 0.72
   */
  $effect(() => {
    if (!audioElement) {
      return;
    }

    audioElement.volume = volume / 100;
  });

  /**
   * Play or pause the real audio according to frontend state.
   *
   * When:
   * - session has audioUrl
   * - app is in playing state
   * - isPlaying is true
   *
   * Then:
   * - try to play the audio.
   *
   * Some browsers block autoplay.
   * That is why native audio controls are shown too.
   */
  $effect(() => {
    if (!audioElement || !audioUrl) {
      return;
    }

    if (canControl && isPlaying) {
      audioElement.play().catch(() => {
        /**
         * Browser may block autoplay until the user clicks play.
         * This is normal browser behavior.
         */
      });
    } else {
      audioElement.pause();
    }
  });

  /**
   * Handle the volume slider.
   *
   * @param {Event} event
   */
  function handleVolumeInput(event) {
    const target = /** @type {HTMLInputElement} */ (event.currentTarget);
    volume = Number(target.value);

    if (audioElement) {
      audioElement.volume = volume / 100;
    }
  }

  /**
 * Convert seconds into a readable audio time format.
 *
 * Example:
 * 84 seconds becomes "1:24"
 *
 * @param {number} seconds
 * @returns {string}
 */
function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "0:00";
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60).toString().padStart(2, "0");

  return `${minutes}:${remainingSeconds}`;
}

function handleLoadedMetadata() {
  if (!audioElement) {
    return;
  }

  duration = Number.isFinite(audioElement.duration) ? audioElement.duration : 0;
}

function handleTimeUpdate() {
  // currentTime itself is kept smooth by the requestAnimationFrame loop
  // above; this just keeps duration in sync as metadata resolves.
  if (!audioElement) {
    return;
  }

  duration = Number.isFinite(audioElement.duration) ? audioElement.duration : 0;
}


/** @param {Event} event */
function handleSeekInput(event) {
  const target = /** @type {HTMLInputElement} */ (event.currentTarget);

  if (!audioElement || duration <= 0) {
    return;
  }

  const percentage = Number(target.value);
  const nextTime = (percentage / 100) * duration;

  audioElement.currentTime = nextTime;
  currentTime = nextTime;
}

function handleAudioEnded() {
  currentTime = duration;
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
      <EqualizerBars active={canControl && isPlaying} />
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
    <button
      class="segment-button"
      disabled
      aria-label="Previous segment"
      title="Previous segment will be available when real segments are added"
    >
      ⏮
    </button>

    <button class="play-button" onclick={onTogglePlay} disabled={!canControl} aria-label="Play or pause AI DJ">
      {isPlaying ? "Ⅱ" : "▶"}
    </button>

    <button
      class="segment-button"
      disabled
      aria-label="Next segment"
      title="Next segment will be available when real segments are added"
    >
      ⏭
    </button>

    <button class="stop-button" onclick={onStop} disabled={!canControl}>
      Stop AI DJ
    </button>
  </div>

    <div class="progress-line" aria-label="Current audio progress">
  <span>{formatTime(currentTime)}</span>

  <input
    class="progress-slider"
    type="range"
    min="0"
    max="100"
    step="0.1"
    value={isStarting ? progress : progressPercent}
    oninput={handleSeekInput}
    disabled={!audioUrl || duration <= 0}
    aria-label="Seek audio position"
  />

  <span>{formatTime(duration)}</span>
</div>

    {#if audioUrl}
  <!--
    Hidden real audio element.

    The user does not control this directly.
    The custom Zonix play/pause button above controls this audio element.
  -->
  <!-- svelte-ignore a11y_media_has_caption -->
  <audio
  class="hidden-audio"
  bind:this={audioElement}
  src={audioUrl}
  preload="auto"
  onloadedmetadata={handleLoadedMetadata}
  ontimeupdate={handleTimeUpdate}
  onended={handleAudioEnded}
></audio>
{/if}
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

  .play-button:hover:not(:disabled) {
    box-shadow: var(--shadow-blue), 0 0 28px rgba(59, 130, 246, 0.4);
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

  .stop-button:hover:not(:disabled) {
    border-color: var(--danger);
    color: var(--danger);
    background: rgba(255, 107, 134, 0.08);
  }

  .progress-line {
    gap: 12px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .progress-slider {
  flex: 1;
  height: 6px;
  accent-color: var(--accent-2);
  cursor: pointer;
}

  .progress-slider:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .hidden-audio {
  display: none;
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

  .segment-button {
  width: 46px;
  height: 46px;
  border: 1px solid rgba(125, 183, 255, 0.24);
  border-radius: 999px;
  display: grid;
  place-items: center;
  color: var(--text-soft);
  background: rgba(125, 183, 255, 0.05);
  font-size: 18px;
  font-weight: 900;
}

.segment-button:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}
</style>