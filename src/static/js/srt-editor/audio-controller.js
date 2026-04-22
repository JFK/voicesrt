/** Audio playback methods — uses Alpine `this` for $refs.audio and state. */

var PLAYBACK_RATE_KEY = 'voicesrt.playbackRate';
export var PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

function loadStoredRate() {
    var raw = parseFloat(localStorage.getItem(PLAYBACK_RATE_KEY));
    return PLAYBACK_RATES.indexOf(raw) >= 0 ? raw : 1;
}

export function createAudioController() {
    return {
        playbackRate: loadStoredRate(),
        playbackRates: PLAYBACK_RATES,

        applyPlaybackRate() {
            var audio = this.$refs.audio;
            if (audio) audio.playbackRate = this.playbackRate;
        },

        setPlaybackRate(rate) {
            this.playbackRate = rate;
            localStorage.setItem(PLAYBACK_RATE_KEY, String(rate));
            this.applyPlaybackRate();
        },

        togglePlay() {
            var audio = this.$refs.audio;
            if (!audio || !this.audioReady) return;
            if (audio.paused) {
                // Explicit global-play mode: clear any stale preview window
                // so onTimeUpdate does not pause mid-playback, and so the
                // auto-scroll branch re-activates.
                this._previewEnd = null;
                if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
                audio.play();
            } else {
                audio.pause();
                this._previewEnd = null;
                if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
            }
        },

        onTimeUpdate() {
            var audio = this.$refs.audio;
            if (!audio) return;
            // Segment-preview pause: the setTimeout in playSegment is scheduled
            // off wall-clock at play-start, so it misfires when playbackRate
            // changes mid-playback or the audio is seeked elsewhere. Polling
            // currentTime here is the authoritative signal — it pauses at the
            // real boundary regardless of timing drift.
            if (this._previewEnd !== null && audio.currentTime >= this._previewEnd) {
                audio.pause();
                this._previewEnd = null;
                if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
            }
            // Round to 0.1s — timeupdate fires up to 60Hz; integer-second
            // displays would otherwise re-render every frame.
            var t = Math.round(audio.currentTime * 10) / 10;
            if (t === this.currentTime) return;
            this.currentTime = t;
            var found = null;
            for (var i = 0; i < this.segments.length; i++) {
                if (t >= this.segments[i].start && t < this.segments[i].end) {
                    found = i;
                    break;
                }
            }
            if (found !== this.activeSegmentIdx) {
                this.activeSegmentIdx = found;
                // Auto-scroll only during global playback. During single-segment
                // preview (_previewEnd is set) keep the viewport still so the
                // user's editing context isn't yanked away.
                if (found !== null && this._previewEnd === null) {
                    var el = document.getElementById('seg-' + found);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            }
        },

        playSegment(start, end) {
            var audio = this.$refs.audio;
            if (!audio || !this.audioReady) return;
            if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
            // Record the preview boundary before play() so onTimeUpdate (which
            // may fire synchronously on seek) can enforce it.
            this._previewEnd = end;
            audio.currentTime = start;
            audio.play();
            // setTimeout as primary: wall-clock scheduling is precise at 60Hz
            // while timeupdate can lag up to 250ms. onTimeUpdate is the
            // safety net for rate changes, seeks, and startup jitter.
            var rate = audio.playbackRate || 1;
            var duration = ((end - start) * 1000) / rate;
            var self = this;
            this._stopTimer = setTimeout(function () {
                if (self._previewEnd !== null) {
                    audio.pause();
                    self._previewEnd = null;
                }
                self._stopTimer = null;
            }, duration);
        },
    };
}
