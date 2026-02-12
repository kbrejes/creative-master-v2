import { useState, useRef, useEffect, useCallback } from "react";
import iphoneFrame from "./assets/iphone-frame.png";

const API = window.location.hostname === "localhost" ? "http://localhost:8899" : "";

const LANGUAGES = [
  { value: "en", label: "English", flag: "🇺🇸" },
  { value: "ru", label: "Русский", flag: "🇷🇺" },
  { value: "es", label: "Español", flag: "🇪🇸" },
  { value: "fr", label: "Français", flag: "🇫🇷" },
  { value: "de", label: "Deutsch", flag: "🇩🇪" },
  { value: "pt", label: "Português", flag: "🇧🇷" },
  { value: "it", label: "Italiano", flag: "🇮🇹" },
];

const DURATIONS = [
  { value: 30, label: "30s", description: "Quick teaser" },
  { value: 60, label: "60s", description: "Standard" },
  { value: 90, label: "90s", description: "Extended" },
];

// Detect if input is a Telegram channel
function isTelegramInput(input) {
  const t = input.trim();
  if (t.startsWith("@")) return true;
  if (/^https?:\/\/t\.me\//i.test(t)) return true;
  if (/^t\.me\//i.test(t)) return true;
  return false;
}

// =============================================================================
// Psychedelic Placeholder Component
// =============================================================================

function KaleidoscopePlaceholder() {
  return (
    <div style={S.kaleidoscope}>
      <div className="kaleidoscope-inner" />
    </div>
  );
}

// =============================================================================
// Main App
// =============================================================================

function App() {
  // UI State
  const [phase, setPhase] = useState("input"); // input | telegram-posts | language | duration | generating | ready
  const [url, setUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [duration, setDuration] = useState(30);

  // Telegram state
  const [telegramPosts, setTelegramPosts] = useState([]);
  const [selectedPost, setSelectedPost] = useState(null);
  const [telegramLoading, setTelegramLoading] = useState(false);
  const [contentForGeneration, setContentForGeneration] = useState(""); // URL or post text

  // Generated content
  const [shots, setShots] = useState([]); // [{ sub, tts, video_options, selected_video, audio_file, audio_duration }]
  const [music, setMusic] = useState(null);
  const [currentShot, setCurrentShot] = useState(0);

  // CTA state (for Telegram videos)
  const [ctaStatus, setCtaStatus] = useState("idle"); // idle | generating | ready | error
  const [ctaVideoUrl, setCtaVideoUrl] = useState(null);

  // Playback
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef(null);
  const audioRef = useRef(null);
  const musicRef = useRef(null);
  const phoneRef = useRef(null);
  const playingAudioRef = useRef(null); // Track which audio file is currently playing

  // Editing
  const [editingShot, setEditingShot] = useState(null);
  const [editText, setEditText] = useState("");

  // Controls
  const [musicVolume, setMusicVolume] = useState(0.15);
  const [voiceIndex, setVoiceIndex] = useState(0);
  const [subtitleY, setSubtitleY] = useState(0.75); // 0-1, position from top

  // Available options (fetched once)
  const [voices, setVoices] = useState([]);
  const [musicTracks, setMusicTracks] = useState([]);
  const [musicIndex, setMusicIndex] = useState(0);

  // Restore state from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem("preview_state");
      if (saved) {
        const state = JSON.parse(saved);
        if (state.phase === "ready" && state.shots?.length > 0) {
          setPhase(state.phase);
          setUrl(state.url || "");
          setLanguage(state.language || "en");
          setShots(state.shots || []);
          setMusic(state.music || null);
          setCurrentShot(state.currentShot || 0);
          setMusicVolume(state.musicVolume ?? 0.15);
          setMusicIndex(state.musicIndex || 0);
        }
      }
    } catch (e) {
      console.warn("Failed to restore state:", e);
    }
  }, []);

  // Save state to localStorage when ready
  useEffect(() => {
    if (phase === "ready" && shots.length > 0) {
      const state = { phase, url, language, shots, music, currentShot, musicVolume, musicIndex };
      localStorage.setItem("preview_state", JSON.stringify(state));
    }
  }, [phase, url, language, shots, music, currentShot, musicVolume, musicIndex]);

  // Fetch voices and music on mount
  useEffect(() => {
    fetch(`${API}/api/voices?language=en`)
      .then(r => r.json())
      .then(data => setVoices(data.voices || []))
      .catch(() => {});

    fetch(`${API}/api/music`)
      .then(r => r.json())
      .then(data => {
        const allTracks = Object.values(data).flat();
        setMusicTracks(allTracks);
      })
      .catch(() => {});
  }, []);

  // Handle URL submit
  const handleUrlSubmit = async () => {
    if (!url.trim()) return;

    if (isTelegramInput(url)) {
      // Fetch Telegram posts
      setTelegramLoading(true);
      setPhase("telegram-posts");
      try {
        const resp = await fetch(`${API}/api/telegram/top-posts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ channel: url, page_size: 20 }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to load posts");
        setTelegramPosts(data.posts || []);
        if (data.posts?.length > 0) {
          setSelectedPost(data.posts[0]);
        }
      } catch (e) {
        console.error("Telegram fetch failed:", e);
        setPhase("input");
      } finally {
        setTelegramLoading(false);
      }
    } else {
      // Regular URL - go to language selection
      setContentForGeneration(url);
      setPhase("language");
    }
  };

  // Handle Telegram post selection
  const handlePostSelect = () => {
    if (!selectedPost?.text) return;
    setContentForGeneration(selectedPost.text);
    setPhase("language");
  };

  // Handle language selection - go to duration selection
  const handleLanguageSelect = (lang) => {
    setLanguage(lang);
    setPhase("duration");
  };

  // Handle duration selection - start generation
  const handleDurationSelect = async (dur) => {
    setDuration(dur);
    setPhase("generating");
    setShots([]);
    setCurrentShot(0);
    setPlaying(true); // Auto-play during generation
    playingAudioRef.current = null; // Reset audio tracking
    setCtaStatus("idle");
    setCtaVideoUrl(null);

    // Determine if we're using URL or direct content
    const isDirectContent = !contentForGeneration.startsWith("http");
    // Get currently selected voice (if any)
    const selectedVoice = voices[voiceIndex]?.voice_id;
    const isTelegram = isTelegramInput(url);
    const body = isDirectContent
      ? { content: contentForGeneration, language, duration: dur, voice: selectedVoice, telegram_channel: isTelegram ? url : "" }
      : { url: contentForGeneration, language, duration: dur, voice: selectedVoice };

    console.log("[DEBUG] Generation request:", { isDirectContent, isTelegram, telegram_channel: body.telegram_channel, url });

    // If Telegram, start CTA generation indicator
    if (isTelegram) {
      setCtaStatus("generating");
    }

    try {
      const resp = await fetch(`${API}/api/generate-live`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));

            if (evt.type === "music") {
              setMusic(evt.track);
              // Start playing music IMMEDIATELY
              if (musicRef.current && evt.track?.url) {
                musicRef.current.src = evt.track.url;
                musicRef.current.volume = musicVolume;
                musicRef.current.loop = true;
                musicRef.current.play().catch(() => {});
              }
            } else if (evt.type === "sub") {
              setShots(prev => {
                const updated = [...prev];
                while (updated.length <= evt.shot) {
                  updated.push({ sub: "", video_options: [], selected_video: null, audio_file: null });
                }
                updated[evt.shot] = { ...updated[evt.shot], sub: evt.text };
                return updated;
              });
            } else if (evt.type === "audio") {
              // Just store the audio - don't play immediately
              // Audio plays when it's the current shot's turn (handled by effect)
              setShots(prev => {
                const updated = [...prev];
                if (updated[evt.shot]) {
                  updated[evt.shot] = {
                    ...updated[evt.shot],
                    audio_file: evt.file,
                    audio_duration: evt.duration,
                  };
                }
                return updated;
              });
            } else if (evt.type === "video") {
              setShots(prev => {
                const updated = [...prev];
                if (updated[evt.shot]) {
                  updated[evt.shot] = {
                    ...updated[evt.shot],
                    video_options: evt.options,
                    selected_video: evt.options?.[0] || null,
                  };
                }
                return updated;
              });
            } else if (evt.type === "cta") {
              // CTA video event from Telegram workflow
              if (evt.status === "generating") {
                setCtaStatus("generating");
              } else if (evt.status === "ready" && evt.video_url) {
                setCtaStatus("ready");
                setCtaVideoUrl(evt.video_url);
              } else if (evt.status === "error") {
                setCtaStatus("error");
              }
            } else if (evt.type === "done") {
              setPhase("ready");
            } else if (evt.type === "error") {
              console.error("Generation error:", evt.error);
              setPhase("input");
            }
          } catch (e) {
            // Ignore parse errors
          }
        }
      }
    } catch (e) {
      console.error("Generation failed:", e);
      setPhase("input");
    }
  };

  // Effect: Play audio for current shot when both video and audio are ready (during generation)
  // This ensures shots play sequentially like a film, not choppy cuts
  useEffect(() => {
    if (phase !== "generating") return;
    if (!playing) return; // Don't play if user paused

    const currentShotData = shots[currentShot];
    if (!currentShotData) return;

    // Wait for BOTH video and audio to be ready
    if (!currentShotData.audio_file) return;
    if (!currentShotData.selected_video) return;

    // Already playing this audio file? Skip
    if (currentShotData.audio_file === playingAudioRef.current) return;

    // Both ready - start playback for this shot
    if (musicRef.current) musicRef.current.volume = musicVolume * 0.15;
    audioRef.current.src = `${API}/vo/${currentShotData.audio_file}`;
    audioRef.current.play().catch(() => {});
    playingAudioRef.current = currentShotData.audio_file;
  }, [phase, currentShot, shots, musicVolume, playing]);

  // Playback control
  const shot = shots[currentShot] || null;

  // Helper to resolve video URL (handle relative paths for local videos)
  const resolveVideoUrl = (url) => {
    if (!url) return null;
    // If it's already an absolute URL, use it directly
    if (url.startsWith("http://") || url.startsWith("https://")) return url;
    // For relative paths (local videos), prepend API base
    return `${API}${url}`;
  };

  // Shot navigation
  const handleShotChange = (direction) => {
    const newShot = currentShot + direction;
    // Allow navigation to CTA shot (at index shots.length) if CTA is ready
    const hasCta = ctaStatus === "ready" && ctaVideoUrl;
    const maxShot = shots.length + (hasCta ? 1 : 0) - 1;
    if (newShot >= 0 && newShot <= maxShot) {
      setCurrentShot(newShot);
    }
  };

  useEffect(() => {
    if (!shot || phase !== "ready") return;

    // Load video
    if (videoRef.current && shot.selected_video?.stream_url) {
      videoRef.current.src = resolveVideoUrl(shot.selected_video.stream_url);
      videoRef.current.load();
      if (playing) videoRef.current.play().catch(() => {});
    }

    // Load audio
    if (audioRef.current && shot.audio_file) {
      audioRef.current.src = `${API}/vo/${shot.audio_file}`;
      audioRef.current.load();
      if (playing) audioRef.current.play().catch(() => {});
    }
  }, [currentShot, shot, playing, phase]);

  const handleAudioEnd = useCallback(() => {
    // Restore music volume after voice ends
    if (musicRef.current) musicRef.current.volume = musicVolume;
    // Reset audio tracking so next shot can play
    playingAudioRef.current = null;

    // During generation: auto-advance to next shot
    if (phase === "generating") {
      if (currentShot < shots.length - 1) {
        // More regular shots to play
        setCurrentShot(prev => prev + 1);
      } else if (ctaStatus === "ready" && ctaVideoUrl && currentShot === shots.length - 1) {
        // Last regular shot done, CTA is ready - advance to CTA (index = shots.length)
        setCurrentShot(shots.length);
      } else {
        // At the last shot, no CTA yet - mark as "finished playback" so audio doesn't replay
        playingAudioRef.current = shots[currentShot]?.audio_file || "done";
      }
      return;
    }

    // Ready phase: advance or loop back
    if (currentShot < shots.length - 1) {
      setCurrentShot(prev => prev + 1);
    } else {
      // End of all shots - stop everything
      setPlaying(false);
      setCurrentShot(0);
      musicRef.current?.pause();
      if (musicRef.current) musicRef.current.currentTime = 0;
    }
  }, [currentShot, shots.length, shots, phase, musicVolume, ctaStatus, ctaVideoUrl]);

  const togglePlay = () => {
    if (playing) {
      setPlaying(false);
      videoRef.current?.pause();
      audioRef.current?.pause();
      musicRef.current?.pause();
    } else {
      setPlaying(true);
      // If at first shot, restart music from beginning
      if (currentShot === 0 && musicRef.current) {
        musicRef.current.currentTime = 0;
      }
      videoRef.current?.play().catch(() => {});
      audioRef.current?.play().catch(() => {});
      musicRef.current?.play().catch(() => {});
    }
  };

  // Swipe to change video
  const handleSwipeVideo = (direction) => {
    if (!shot?.video_options?.length) return;
    const currentIdx = shot.video_options.findIndex(v => v.pexels_id === shot.selected_video?.pexels_id);
    let newIdx = currentIdx + direction;
    if (newIdx < 0) newIdx = shot.video_options.length - 1;
    if (newIdx >= shot.video_options.length) newIdx = 0;

    setShots(prev => {
      const updated = [...prev];
      updated[currentShot] = { ...updated[currentShot], selected_video: shot.video_options[newIdx] };
      return updated;
    });
  };

  // Edit subtitle text
  const handleSubtitleTap = () => {
    if (!shot) return;
    setEditingShot(currentShot);
    setEditText(shot.sub);
  };

  const handleSubtitleSave = () => {
    if (editingShot === null) return;
    setShots(prev => {
      const updated = [...prev];
      updated[editingShot] = { ...updated[editingShot], sub: editText };
      return updated;
    });
    setEditingShot(null);
    setEditText("");
  };

  // Music/Voice controls
  const handleMusicChange = (direction) => {
    if (!musicTracks.length) return;
    let newIdx = musicIndex + direction;
    if (newIdx < 0) newIdx = musicTracks.length - 1;
    if (newIdx >= musicTracks.length) newIdx = 0;
    setMusicIndex(newIdx);
    const newTrack = musicTracks[newIdx];
    setMusic(newTrack);
    if (musicRef.current && newTrack?.url) {
      musicRef.current.src = newTrack.url;
      musicRef.current.volume = musicVolume;
      if (playing) musicRef.current.play().catch(() => {});
    }
  };

  const handleVoiceChange = (direction) => {
    if (!voices.length) return;
    let newIdx = voiceIndex + direction;
    if (newIdx < 0) newIdx = voices.length - 1;
    if (newIdx >= voices.length) newIdx = 0;
    setVoiceIndex(newIdx);
    // TODO: Regenerate audio with new voice
  };

  // Sidechain ducking
  useEffect(() => {
    const vo = audioRef.current;
    const m = musicRef.current;
    if (!vo || !m) return;

    const duck = () => { m.volume = musicVolume * 0.15; };
    const unduck = () => { m.volume = musicVolume; };

    vo.addEventListener("play", duck);
    vo.addEventListener("pause", unduck);
    vo.addEventListener("ended", unduck);
    return () => {
      vo.removeEventListener("play", duck);
      vo.removeEventListener("pause", unduck);
      vo.removeEventListener("ended", unduck);
    };
  }, [musicVolume]);

  useEffect(() => {
    if (musicRef.current) musicRef.current.volume = musicVolume;
  }, [musicVolume]);

  // Reset function
  const handleReset = () => {
    setPhase("input");
    setUrl("");
    setShots([]);
    setMusic(null);
    setCurrentShot(0);
    setPlaying(false);
    musicRef.current?.pause();
    localStorage.removeItem("preview_state");
  };

  // Save video - render and download
  const [saving, setSaving] = useState(false);
  const handleSave = async () => {
    if (saving || shots.length === 0) return;
    setSaving(true);
    try {
      // Collect all shot data for rendering
      const shotData = shots.map((s, i) => ({
        sub: s.sub,
        audio_file: s.audio_file,
        video_url: s.selected_video?.stream_url,
        duration: s.audio_duration || 3,
      }));
      console.log("Saving shots:", shotData);

      const resp = await fetch(`${API}/api/save-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          shots: shotData,
          music: music,
          language,
          subtitle_y: subtitleY,
          telegram_channel: isTelegramInput(url) ? url : "",
        }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        alert(err.error || "Failed to render video");
        return;
      }

      const data = await resp.json();
      if (data.video_url) {
        // Download the video - need full URL for cross-origin
        const fullUrl = `${API}${data.video_url}`;
        console.log("Downloading from:", fullUrl);

        // Fetch and create blob for proper download
        const videoResp = await fetch(fullUrl);
        const blob = await videoResp.blob();
        const blobUrl = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = "video.mp4";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);
      }
    } catch (e) {
      console.error("Save failed:", e);
      alert("Failed to save video: " + e.message);
    } finally {
      setSaving(false);
    }
  };

  // Screen insets for iPhone frame
  const screenInset = { left: "6.5%", right: "6.6%", top: "8.15%", bottom: "3.3%" };

  // Render phone content based on phase
  const renderPhoneContent = () => {
    // INPUT PHASE: URL input
    if (phase === "input") {
      return (
        <div style={S.inputOverlay}>
          <div style={S.inputBlob}>
            <div className="morph-blob" />
          </div>
          <div style={S.inputHeading}>Create a Video Ad</div>
          <div style={S.inputDescription}>
            Paste a landing page, article, or Telegram post — get a ready-to-publish Reels, TikTok, or Short in seconds
          </div>
          <div style={S.inputPointer}>👇</div>
          <input
            type="text"
            placeholder="https://..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleUrlSubmit()}
            style={S.urlInput}
            autoFocus
          />
          <button style={S.nextBtn} onClick={handleUrlSubmit} disabled={!url.trim()}>
            Next →
          </button>
        </div>
      );
    }

    // TELEGRAM POSTS PHASE: Post picker
    if (phase === "telegram-posts") {
      return (
        <div style={S.postsOverlay}>
          <div style={S.inputTitle}>Pick a post</div>
          {telegramLoading ? (
            <div style={{ textAlign: "center", padding: 40 }}>
              <div className="kaleidoscope-inner" style={{ width: 60, height: 60, margin: "0 auto", borderRadius: "50%" }} />
            </div>
          ) : (
            <>
              <div style={S.postsList}>
                {telegramPosts.map((post) => (
                  <div
                    key={post.message_id}
                    style={{
                      ...S.postItem,
                      borderColor: selectedPost?.message_id === post.message_id ? "#4f46e5" : "#333",
                      background: selectedPost?.message_id === post.message_id ? "#1e1b4b" : "#1a1a1a",
                    }}
                    onClick={() => setSelectedPost(post)}
                  >
                    <div style={S.postText}>
                      {post.text?.slice(0, 100) || "(No text)"}
                      {post.text?.length > 100 ? "..." : ""}
                    </div>
                    <div style={S.postMeta}>
                      <span>👁 {post.views?.toLocaleString()}</span>
                      <span>↗ {post.forwards}</span>
                      {post.total_reactions > 0 && <span>❤️ {post.total_reactions}</span>}
                    </div>
                  </div>
                ))}
              </div>
              <button
                style={{ ...S.nextBtn, marginTop: 12 }}
                onClick={handlePostSelect}
                disabled={!selectedPost}
              >
                Use this post →
              </button>
            </>
          )}
        </div>
      );
    }

    // LANGUAGE PHASE: Language picker
    if (phase === "language") {
      return (
        <div style={S.languageOverlay}>
          <div style={S.inputTitle}>Choose language</div>
          <div style={S.languageGrid}>
            {LANGUAGES.map((lang) => (
              <button
                key={lang.value}
                style={S.languageBtn}
                onClick={() => handleLanguageSelect(lang.value)}
              >
                <span style={{ fontSize: 24 }}>{lang.flag}</span>
                <span style={{ fontSize: 12, marginTop: 4 }}>{lang.label}</span>
              </button>
            ))}
          </div>
        </div>
      );
    }

    if (phase === "duration") {
      return (
        <div style={S.languageOverlay}>
          <div style={S.inputTitle}>Choose duration</div>
          <div style={S.languageGrid}>
            {DURATIONS.map((d) => (
              <button
                key={d.value}
                style={S.languageBtn}
                onClick={() => handleDurationSelect(d.value)}
              >
                <span style={{ fontSize: 24 }}>{d.label}</span>
                <span style={{ fontSize: 10, marginTop: 4, opacity: 0.7 }}>{d.description}</span>
              </button>
            ))}
          </div>
        </div>
      );
    }

    // GENERATING PHASE: Show current shot only (others generate silently in background)
    if (phase === "generating") {
      // Check if we're on the CTA shot (index = shots.length)
      const isCtaShot = currentShot === shots.length && ctaStatus === "ready" && ctaVideoUrl;
      const currentShotData = shots[currentShot];
      const videoUrl = isCtaShot
        ? ctaVideoUrl
        : (currentShotData?.selected_video?.stream_url || currentShotData?.selected_video?.url);
      const currentSub = isCtaShot ? "" : (currentShotData?.sub || "");
      const shotsWithVideo = shots.filter(s => s.selected_video).length;
      const hasVideoOptions = !isCtaShot && currentShotData?.video_options?.length > 1;
      const totalWithCta = shots.length + (ctaStatus === "ready" ? 1 : 0);

      return (
        <>
          {videoUrl ? (
            <video
              ref={videoRef}
              key={videoUrl}
              src={isCtaShot ? `${API}${ctaVideoUrl}` : resolveVideoUrl(videoUrl)}
              style={S.video}
              muted
              playsInline
              loop={!isCtaShot} // CTA doesn't loop - plays once
              autoPlay
              onClick={togglePlay}
            />
          ) : (
            <KaleidoscopePlaceholder />
          )}
          {currentSub && (
            <div style={{ ...S.subOverlay, top: `${subtitleY * 100}%`, bottom: "auto", transform: "translateY(-50%)" }}>
              <span style={S.subText}>{currentSub}</span>
            </div>
          )}
          {isCtaShot && (
            <div style={S.ctaLabel}>CTA - Telegram Channel</div>
          )}

          {/* Shot navigation - can browse already generated shots */}
          <div style={S.shotNav}>
            <button
              style={{ ...S.shotNavBtn, opacity: currentShot > 0 ? 1 : 0.3 }}
              onClick={() => handleShotChange(-1)}
              disabled={currentShot === 0}
            >
              ◀
            </button>
            <span style={S.shotBadgeInline}>
              {currentShot + 1}/{totalWithCta || 1}{isCtaShot ? " CTA" : ""}
            </span>
            <button
              style={{ ...S.shotNavBtn, opacity: currentShot < totalWithCta - 1 ? 1 : 0.3 }}
              onClick={() => handleShotChange(1)}
              disabled={currentShot >= totalWithCta - 1}
            >
              ▶
            </button>
          </div>

          {/* Generating badge */}
          <div style={S.generatingBadge}>
            {isCtaShot
              ? "✨ CTA Ready"
              : shotsWithVideo === shots.length && shots.length > 0
                ? "✨ Finishing..."
                : `⏳ ${shotsWithVideo}/${shots.length || "..."} ready`}
          </div>

          {/* Play/pause indicator */}
          {!playing && videoUrl && <div style={S.playIcon} onClick={togglePlay}>▶</div>}

          {/* Swipe to change video (if multiple options) */}
          {hasVideoOptions && (
            <div style={S.swipeHint}>
              <button style={S.swipeBtn} onClick={() => handleSwipeVideo(-1)}>◀</button>
              <span style={{ fontSize: 10, color: "#888" }}>swipe video</span>
              <button style={S.swipeBtn} onClick={() => handleSwipeVideo(1)}>▶</button>
            </div>
          )}

          {ctaStatus === "generating" && !isCtaShot && (
            <div style={S.ctaLoading}>
              <span className="spinner">⏳</span>
              <span>Recording CTA...</span>
            </div>
          )}
        </>
      );
    }

    // READY PHASE: Full preview
    // Check if we're viewing the CTA shot (last position when CTA exists)
    const hasCta = ctaStatus === "ready" && ctaVideoUrl;
    const totalShots = shots.length + (hasCta ? 1 : 0);
    const isCtaShot = hasCta && currentShot === shots.length;

    if (phase === "ready" && isCtaShot) {
      // Display CTA video
      return (
        <>
          <video
            ref={videoRef}
            src={`${API}${ctaVideoUrl}`}
            style={S.video}
            muted
            playsInline
            loop
            autoPlay
          />
          <div style={S.ctaLabel}>CTA - Telegram Channel</div>

          {/* Shot indicator with navigation arrows */}
          <div style={S.shotNav}>
            <button
              style={{ ...S.shotNavBtn, opacity: currentShot > 0 ? 1 : 0.3 }}
              onClick={() => handleShotChange(-1)}
              disabled={currentShot === 0}
            >
              ◀
            </button>
            <span style={S.shotBadgeInline}>{currentShot + 1}/{totalShots} CTA</span>
            <button style={{ ...S.shotNavBtn, opacity: 0.3 }} disabled>▶</button>
          </div>
        </>
      );
    }

    if (phase === "ready" && shot) {
      const hasVideo = shot.selected_video?.stream_url;

      return (
        <>
          {/* Video or placeholder */}
          {hasVideo ? (
            <video
              ref={videoRef}
              style={S.video}
              muted
              playsInline
              loop
              onClick={togglePlay}
            />
          ) : (
            <KaleidoscopePlaceholder />
          )}

          {/* Subtitle - tappable to edit */}
          {editingShot === currentShot ? (
            <div style={S.editOverlay}>
              <textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                style={S.editTextarea}
                autoFocus
              />
              <button style={S.editSaveBtn} onClick={handleSubtitleSave}>
                Done
              </button>
            </div>
          ) : (
            <div style={{ ...S.subOverlay, top: `${subtitleY * 100}%`, bottom: "auto", transform: "translateY(-50%)" }} onClick={handleSubtitleTap}>
              <span style={S.subText}>{shot.sub}</span>
            </div>
          )}

          {/* Shot indicator with navigation arrows */}
          <div style={S.shotNav}>
            <button
              style={{ ...S.shotNavBtn, opacity: currentShot > 0 ? 1 : 0.3 }}
              onClick={() => handleShotChange(-1)}
              disabled={currentShot === 0}
            >
              ◀
            </button>
            <span style={S.shotBadgeInline}>{currentShot + 1}/{totalShots}</span>
            <button
              style={{ ...S.shotNavBtn, opacity: currentShot < totalShots - 1 ? 1 : 0.3 }}
              onClick={() => handleShotChange(1)}
              disabled={currentShot === totalShots - 1}
            >
              ▶
            </button>
          </div>

          {/* Play indicator */}
          {!playing && <div style={S.playIcon} onClick={togglePlay}>▶</div>}

          {/* Swipe hint for video options */}
          <div style={S.swipeHint}>
            <button style={S.swipeBtn} onClick={() => handleSwipeVideo(-1)}>◀</button>
            <span style={{ fontSize: 10, color: "#888" }}>swipe video</span>
            <button style={S.swipeBtn} onClick={() => handleSwipeVideo(1)}>▶</button>
          </div>
        </>
      );
    }

    return null;
  };

  return (
    <div style={S.container}>
      {/* Hidden audio elements */}
      <audio ref={audioRef} onEnded={handleAudioEnd} />
      <audio ref={musicRef} />

      {/* Phone Frame */}
      <div style={S.phoneWrapper}>
        <img src={iphoneFrame} alt="" style={S.phoneFrame} />
        <div ref={phoneRef} style={{ ...S.phoneScreen, ...screenInset }}>
          {renderPhoneContent()}
        </div>
      </div>

      {/* Controls below phone (visible during generating and ready) */}
      {(phase === "generating" || phase === "ready") && (
        <div style={S.controlsBelow}>
          {/* Voice selector */}
          <div style={{ ...S.controlRow, opacity: phase === "ready" ? 1 : 0.5 }}>
            <button style={S.controlBtn} onClick={() => handleVoiceChange(-1)} disabled={phase !== "ready"}>◀</button>
            <span style={S.controlLabel}>
              🎙 {voices[voiceIndex]?.name || "Voice"}
            </span>
            <button style={S.controlBtn} onClick={() => handleVoiceChange(1)} disabled={phase !== "ready"}>▶</button>
          </div>

          {/* Music selector */}
          <div style={S.controlRow}>
            <button style={S.controlBtn} onClick={() => handleMusicChange(-1)}>◀</button>
            <span style={S.controlLabel}>
              🎵 {music?.name || "Music"}
            </span>
            <button style={S.controlBtn} onClick={() => handleMusicChange(1)}>▶</button>
          </div>

          {/* Music volume */}
          <div style={S.volumeRow}>
            <span style={{ fontSize: 11, color: "#666" }}>Volume</span>
            <input
              type="range"
              min="0"
              max="0.5"
              step="0.01"
              value={musicVolume}
              onChange={(e) => setMusicVolume(parseFloat(e.target.value))}
              style={{ width: 100, accentColor: "#4f46e5" }}
            />
          </div>

          {/* Subtitle position */}
          <div style={S.volumeRow}>
            <span style={{ fontSize: 11, color: "#666" }}>Subs ↕</span>
            <input
              type="range"
              min="0.3"
              max="0.9"
              step="0.01"
              value={subtitleY}
              onChange={(e) => setSubtitleY(parseFloat(e.target.value))}
              style={{ width: 100, accentColor: "#4f46e5" }}
            />
          </div>

          {/* Save button */}
          <button
            style={{ ...S.saveBtn, opacity: phase === "ready" ? 1 : 0.5 }}
            onClick={handleSave}
            disabled={saving || phase !== "ready"}
          >
            {saving ? "⏳ Rendering..." : phase === "ready" ? "💾 Save to Camera Roll" : "⏳ Generating..."}
          </button>

          {/* Reset */}
          <button style={S.resetBtn} onClick={handleReset}>
            Start Over
          </button>
        </div>
      )}

      {/* CSS */}
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; background: #0a0a0a; }

        .kaleidoscope-inner {
          position: absolute;
          inset: 0;
          background: linear-gradient(45deg, #ff006e, #8338ec, #3a86ff, #06ffa5, #ffbe0b);
          background-size: 400% 400%;
          animation: kaleidoscope-move 8s ease-in-out infinite, kaleidoscope-hue 12s linear infinite;
          filter: blur(30px) saturate(1.5);
        }

        @keyframes kaleidoscope-move {
          0%, 100% { background-position: 0% 50%; }
          25% { background-position: 100% 0%; }
          50% { background-position: 100% 100%; }
          75% { background-position: 0% 100%; }
        }

        @keyframes kaleidoscope-hue {
          0% { filter: blur(30px) saturate(1.5) hue-rotate(0deg); }
          100% { filter: blur(30px) saturate(1.5) hue-rotate(360deg); }
        }

        .morph-blob {
          width: 100%;
          height: 100%;
          position: relative;
          background: linear-gradient(135deg, #ff073a, #bf00ff, #0040ff);
          background-size: 300% 300%;
          animation: morph-shape 4s ease-in-out infinite, morph-gradient 6s ease infinite;
          box-shadow: 0 0 25px #bf00ff66, 0 0 50px #ff073a33;
        }

        @keyframes morph-shape {
          0%   { border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%; }
          25%  { border-radius: 30% 60% 70% 40% / 50% 60% 30% 60%; }
          50%  { border-radius: 50% 60% 30% 60% / 30% 40% 70% 60%; }
          75%  { border-radius: 60% 30% 60% 40% / 70% 50% 40% 60%; }
          100% { border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%; }
        }

        @keyframes morph-gradient {
          0%   { background-position: 0% 50%; }
          50%  { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
      `}</style>
    </div>
  );
}

// =============================================================================
// Styles
// =============================================================================

const S = {
  container: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
    fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
    color: "#fff",
    background: "#0a0a0a",
  },
  phoneWrapper: {
    position: "relative",
    width: "100%",
    maxWidth: 320,
    aspectRatio: "1520 / 3068", // Match iPhone frame image dimensions
  },
  phoneFrame: {
    width: "100%",
    height: "100%",
    display: "block",
    position: "absolute",
    top: 0,
    left: 0,
    zIndex: 2,
    pointerEvents: "none",
    objectFit: "contain",
  },
  phoneScreen: {
    position: "absolute",
    zIndex: 1,
    borderRadius: "8%",
    overflow: "hidden",
    background: "#000",
  },
  // Input overlay
  inputOverlay: {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    background: "linear-gradient(180deg, #1a1a2e 0%, #0f0f1a 100%)",
  },
  inputTitle: {
    fontSize: 18,
    fontWeight: 600,
    marginBottom: 20,
    color: "#fff",
  },
  inputBlob: {
    width: 80,
    height: 80,
    borderRadius: "50%",
    overflow: "hidden",
    marginBottom: 20,
    position: "relative",
  },
  inputHeading: {
    fontSize: 22,
    fontWeight: 700,
    color: "#fff",
    marginBottom: 8,
    textAlign: "center",
  },
  inputDescription: {
    fontSize: 13,
    color: "#888",
    textAlign: "center",
    lineHeight: 1.4,
    marginBottom: 8,
    padding: "0 8px",
  },
  inputPointer: {
    fontSize: 24,
    marginBottom: 16,
  },
  urlInput: {
    width: "100%",
    padding: "12px 16px",
    fontSize: 16,
    borderRadius: 12,
    border: "1px solid #333",
    background: "#222",
    color: "#fff",
    outline: "none",
    marginBottom: 16,
  },
  nextBtn: {
    padding: "12px 32px",
    fontSize: 16,
    fontWeight: 600,
    borderRadius: 12,
    border: "none",
    background: "#4f46e5",
    color: "#fff",
    cursor: "pointer",
  },
  // Language overlay
  languageOverlay: {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    background: "linear-gradient(180deg, #1a1a2e 0%, #0f0f1a 100%)",
  },
  languageGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 12,
    width: "100%",
  },
  languageBtn: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: 16,
    borderRadius: 12,
    border: "1px solid #333",
    background: "#1a1a1a",
    color: "#fff",
    cursor: "pointer",
  },
  // Kaleidoscope
  kaleidoscope: {
    position: "absolute",
    inset: 0,
    overflow: "hidden",
  },
  // Video
  video: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  // Subtitle overlay
  subOverlay: {
    position: "absolute",
    bottom: "15%",
    left: 12,
    right: 12,
    textAlign: "center",
    cursor: "pointer",
  },
  subText: {
    background: "rgba(0,0,0,0.7)",
    color: "#fff",
    padding: "8px 16px",
    borderRadius: 8,
    fontSize: 14,
    lineHeight: 1.4,
    display: "inline-block",
    maxWidth: "95%",
  },
  ctaLabel: {
    position: "absolute",
    bottom: 60,
    left: 12,
    right: 12,
    textAlign: "center",
    background: "rgba(0,136,204,0.8)",
    color: "#fff",
    padding: "8px 16px",
    borderRadius: 8,
    fontSize: 12,
    fontWeight: "600",
  },
  ctaLoading: {
    position: "absolute",
    bottom: 20,
    left: 12,
    right: 12,
    textAlign: "center",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    background: "rgba(0,0,0,0.7)",
    color: "#fff",
    padding: "8px 16px",
    borderRadius: 8,
    fontSize: 11,
  },
  // Badges
  shotNav: {
    position: "absolute",
    top: 12,
    right: 12,
    display: "flex",
    alignItems: "center",
    gap: 6,
    background: "rgba(0,0,0,0.6)",
    padding: "4px 8px",
    borderRadius: 16,
  },
  shotNavBtn: {
    width: 24,
    height: 24,
    borderRadius: "50%",
    border: "none",
    background: "rgba(255,255,255,0.2)",
    color: "#fff",
    fontSize: 10,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  shotBadgeInline: {
    color: "#fff",
    fontSize: 12,
    padding: "0 4px",
  },
  shotBadge: {
    position: "absolute",
    top: 12,
    right: 12,
    background: "rgba(0,0,0,0.6)",
    color: "#fff",
    padding: "4px 10px",
    borderRadius: 12,
    fontSize: 12,
  },
  generatingBadge: {
    position: "absolute",
    top: 12,
    left: "50%",
    transform: "translateX(-50%)",
    background: "rgba(79,70,229,0.8)",
    color: "#fff",
    padding: "6px 16px",
    borderRadius: 12,
    fontSize: 12,
    fontWeight: 600,
  },
  playIcon: {
    position: "absolute",
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)",
    fontSize: 48,
    color: "rgba(255,255,255,0.8)",
    textShadow: "0 2px 10px rgba(0,0,0,0.5)",
    cursor: "pointer",
  },
  // Swipe controls
  swipeHint: {
    position: "absolute",
    bottom: 8,
    left: "50%",
    transform: "translateX(-50%)",
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  swipeBtn: {
    width: 28,
    height: 28,
    borderRadius: "50%",
    border: "1px solid #444",
    background: "rgba(0,0,0,0.6)",
    color: "#fff",
    fontSize: 12,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  // Edit overlay
  editOverlay: {
    position: "absolute",
    bottom: "10%",
    left: 12,
    right: 12,
    background: "rgba(0,0,0,0.9)",
    borderRadius: 12,
    padding: 12,
  },
  editTextarea: {
    width: "100%",
    height: 80,
    padding: 10,
    fontSize: 14,
    borderRadius: 8,
    border: "1px solid #444",
    background: "#222",
    color: "#fff",
    resize: "none",
    outline: "none",
    marginBottom: 8,
  },
  editSaveBtn: {
    width: "100%",
    padding: 10,
    fontSize: 14,
    fontWeight: 600,
    borderRadius: 8,
    border: "none",
    background: "#4f46e5",
    color: "#fff",
    cursor: "pointer",
  },
  // Controls below phone
  controlsBelow: {
    marginTop: 20,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 12,
    width: "100%",
    maxWidth: 320,
  },
  controlRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    width: "100%",
    justifyContent: "center",
  },
  controlBtn: {
    width: 32,
    height: 32,
    borderRadius: "50%",
    border: "1px solid #333",
    background: "#1a1a1a",
    color: "#fff",
    fontSize: 12,
    cursor: "pointer",
  },
  controlLabel: {
    fontSize: 13,
    color: "#aaa",
    minWidth: 140,
    textAlign: "center",
  },
  volumeRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  saveBtn: {
    width: "100%",
    padding: 14,
    fontSize: 16,
    fontWeight: 600,
    borderRadius: 12,
    border: "none",
    background: "#059669",
    color: "#fff",
    cursor: "pointer",
    marginTop: 8,
  },
  resetBtn: {
    padding: "8px 16px",
    fontSize: 12,
    borderRadius: 8,
    border: "1px solid #333",
    background: "transparent",
    color: "#666",
    cursor: "pointer",
  },
  // Telegram posts overlay
  postsOverlay: {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    padding: 16,
    background: "linear-gradient(180deg, #1a1a2e 0%, #0f0f1a 100%)",
    overflow: "hidden",
  },
  postsList: {
    flex: 1,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    paddingBottom: 8,
  },
  postItem: {
    padding: 12,
    borderRadius: 10,
    border: "2px solid #333",
    cursor: "pointer",
    transition: "border-color 0.15s, background 0.15s",
  },
  postText: {
    fontSize: 13,
    lineHeight: 1.4,
    color: "#eee",
    marginBottom: 8,
  },
  postMeta: {
    display: "flex",
    gap: 12,
    fontSize: 11,
    color: "#888",
  },
};

export default App;
