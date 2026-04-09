<template>
  <div id="app">
    <nav class="nav">
      <div class="nav-brand">📊 PTA量化分析平台</div>
      <div class="nav-links">
        <router-link to="/">主页</router-link>
        <router-link to="/kline">K线图</router-link>
        <router-link to="/chan">缠论分析</router-link>
      </div>
      <div class="nav-status">
        <span class="status-dot"></span>
        系统正常
      </div>
    </nav>
    <router-view />
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #e6edf3; }
#app { min-height: 100vh; }
.nav {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 0 24px;
  height: 52px;
  display: flex;
  align-items: center;
  gap: 32px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.nav-brand { font-size: 1.1rem; font-weight: 700; color: #e94560; }
.nav-links { display: flex; gap: 20px; }
.nav-links a {
  color: #8b949e;
  text-decoration: none;
  font-size: 0.9rem;
  padding: 6px 12px;
  border-radius: 6px;
  transition: all 0.2s;
}
.nav-links a:hover, .nav-links a.router-link-active {
  color: #fff;
  background: #21262d;
}
.nav-status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: #8b949e;
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #3fb950;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
