<script>
  /**
   * Hero section for Zonix.
   * Keeps the brand promise clear without making the UI confusing.
   */
</script>

<section class="hero-card">
  <div class="wave left" aria-hidden="true"></div>
  <div class="wave right" aria-hidden="true"></div>

  <div class="hero-copy">
    <span class="badge">Get in the zone</span>
    <h1>Your AI DJ.<br /><span>Zero interruptions.</span></h1>
    <p>Music that adapts to you. Flows that keep you in the zone.</p>
  </div>
</section>

<style>
  .hero-card {
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(125, 183, 255, 0.16);
    border-radius: 24px 24px 0 0;
    min-height: 260px;
    display: grid;
    place-items: center;
    margin-top: 8px;
    padding: 70px 28px 42px;
    background:
      radial-gradient(circle at 50% 8%, rgba(59, 130, 246, 0.12), transparent 28%),
      linear-gradient(180deg, rgba(4, 10, 20, 0.9), rgba(3, 8, 16, 0.72));
  }

  .hero-copy {
    position: relative;
    z-index: 2;
    text-align: center;
  }

  h1 {
    margin: 18px 0 16px;
    font-family: var(--font-display);
    font-size: clamp(52px, 7vw, 90px);
    line-height: 0.94;
    letter-spacing: -0.055em;
  }

  h1 span {
    color: transparent;
    background: linear-gradient(90deg, #cde1ff, #3b82f6 74%);
    -webkit-background-clip: text;
    background-clip: text;
  }

  p {
    margin: 0 auto;
    max-width: 720px;
    color: var(--text-soft);
    font-size: 18px;
    line-height: 1.7;
  }

  .wave {
    position: absolute;
    width: 38%;
    height: 160px;
    top: 86px;
    opacity: 0.48;
    background:
      radial-gradient(circle at 50% 50%, rgba(125, 183, 255, 0.32), transparent 24%),
      repeating-radial-gradient(ellipse at center, transparent 0 12px, rgba(125, 183, 255, 0.22) 13px 14px, transparent 15px 26px);
    filter: blur(0.3px);
    mask-image: linear-gradient(90deg, transparent, black 24%, black 78%, transparent);
  }

  .wave.left {
    left: -3%;
    transform: rotate(2deg) scaleY(0.46);
  }

  .wave.right {
    right: -3%;
    transform: rotate(-2deg) scaleY(0.46);
  }

  @media (max-width: 720px) {
    .hero-card {
      min-height: 220px;
      padding: 52px 18px 34px;
    }

    .wave {
      display: none;
    }
  }
</style>
