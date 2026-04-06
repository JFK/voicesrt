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
            if (!audio) return;
            if (audio.paused) {
                audio.play();
            } else {
                audio.pause();
                if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
            }
        },

        onTimeUpdate() {
            var audio = this.$refs.audio;
            if (!audio) return;
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
                if (found !== null) {
                    var el = document.getElementById('seg-' + found);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            }
        },

        playSegment(start, end) {
            var audio = this.$refs.audio;
            if (!audio) return;
            if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
            audio.currentTime = start;
            audio.play();
            // Wall-clock duration scales inversely with playbackRate so 2x
            // finishes the segment in half the time. We snapshot the rate at
            // play start; if the user changes rate mid-segment the timer will
            // be slightly off, which is acceptable for a quick preview.
            var rate = audio.playbackRate || 1;
            var duration = ((end - start) * 1000) / rate;
            var self = this;
            this._stopTimer = setTimeout(function () {
                audio.pause();
                self._stopTimer = null;
            }, duration);
        },
    };
}
