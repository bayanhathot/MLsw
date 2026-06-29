<script>
  /**
   * Purpose:
   * Top navigation for the Smart AI DJ homepage.
   *
   * How this connects to the project:
   * It gives the app a real product identity while keeping the MVP no-login.
   * The sign-in button is intentionally visual for now; login is postponed until
   * save/history/personalization features exist.
   *
   * Engineering decision:
   * Navbar has no state. It is a simple presentational component.
   */
</script>

<nav class="navbar">
  <div class="logo">
    <span class="logo-mark">DJ</span>
    <span>Smart AI DJ Mixer</span>
  </div>

  <div class="links">
    <!-- <a href="/">Explore</a>
    <a href="/">Presets</a> -->
    <button class="secondary-button">Sign in</button>
  </div>
</nav>

<style>
  .navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 22px 0;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 12px;
    font-weight: 800;
  }

  .logo-mark {
    display: grid;
    place-items: center;
    width: 42px;
    height: 42px;
    border-radius: 14px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
  }

  .links {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  a {
    color: var(--text-muted);
    text-decoration: none;
  }

  a:hover {
    color: var(--text-main);
  }

  @media (max-width: 700px) {
    .links a {
      display: none;
    }
  }
</style>
