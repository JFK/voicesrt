/** Audio playback methods — uses Alpine `this` for $refs.audio and state. */

export var PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

export function createAudioController() {
    return {
        playbackRate: 1,
        playbackRates: PLAYBACK_RATES,

        applyPlaybackRate() {
            var audio = this.$refs.audio;
            if (audio) audio.playbackRate = this.playbackRate;
        },

        setPlaybackRate(rate) {
            this.playbackRate = rate;
            this.applyPlaybackRate();
        },

        _cancelPreview() {
            if (this._stopTimer) { clearTimeout(this._stopTimer); this._stopTimer = null; }
            if (this._previewEnd !== null) this._previewEnd = null;
        },

        togglePlay() {
            var audio = this.$refs.audio;
            if (!audio || !this.audioReady) return;
            this._cancelPreview();
            if (audio.paused) audio.play();
            else audio.pause();
        },

        onTimeUpdate() {
            var audio = this.$refs.audio;
            if (!audio) return;
            if (this._previewEnd !== null && audio.currentTime >= this._previewEnd) {
                audio.pause();
                this._cancelPreview();
            }
            // timeupdate fires up to 60Hz; rounding to 0.1s avoids a re-render
            // of the integer-second display every frame.
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
                // Auto-scroll only during global playback; preview keeps the
                // viewport anchored on the segment being edited.
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
            this._previewEnd = end;
            audio.currentTime = start;
            audio.play();
            // setTimeout is the precise primary; onTimeUpdate is a safety net
            // against rate changes, seeks, and play() startup jitter.
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
