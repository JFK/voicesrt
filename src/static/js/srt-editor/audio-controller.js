/** Audio playback methods — uses Alpine `this` for $refs.audio and state. */

export function createAudioController() {
    return {
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

        seekAudio(event) {
            var audio = this.$refs.audio;
            if (!audio || !audio.duration) return;
            var rect = event.currentTarget.getBoundingClientRect();
            var ratio = (event.clientX - rect.left) / rect.width;
            audio.currentTime = ratio * audio.duration;
            if (audio.paused) audio.play();
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
            var duration = (end - start) * 1000;
            var self = this;
            this._stopTimer = setTimeout(function () {
                audio.pause();
                self._stopTimer = null;
            }, duration);
        },
    };
}
