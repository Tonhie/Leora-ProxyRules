// Optional: disables RTCPeerConnection. Browser calls/video meetings may stop working.
// Append to your Firefox profile's user.js only if you want WebRTC disabled.
user_pref("media.peerconnection.enabled", false);

// Use the core-managed DNS through TUN/VPN; do not enable without capture.
user_pref("network.trr.mode", 5);
