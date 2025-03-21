function pingBackend() {
  fetch("https://roadtrack.onrender.com/ping")
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Server responded with status ${response.status}`);
      }
      console.log("✅ Ping successful");
    })
    .catch((error) => {
      console.error("❌ Ping failed:", error.message);
    });
}

// Call it every 5 minutes (300,000 ms)
setInterval(pingBackend, 5 * 60 * 1000);

// Optional: Call it once immediately on page load
pingBackend();
